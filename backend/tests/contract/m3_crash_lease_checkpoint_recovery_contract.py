from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from paperseek_app.errors import RunOwnershipLost
from paperseek_app.execution import WorkflowExecution
from paperseek_app.models import PendingEvent, RunStatus
from paperseek_app.services import RunExecutionService, RunQueryService, RunSubmissionService
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.fixed_source import FixedLLMAdapter, FixedSourceAdapter
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_app.worker import RunExecutor
from paperseek_core.models import QueryLoopBudget, ResearchWorkflowRequest


FIXTURE = Path(__file__).parent / "fixtures" / "m1_fixed_source.json"


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class TrackingSource:
    def __init__(self, *, block_on_search: int | None = None) -> None:
        self.delegate = FixedSourceAdapter.from_file(FIXTURE)
        self.name = self.delegate.name
        self.capabilities = self.delegate.capabilities
        self.fixture = self.delegate.fixture
        self.block_on_search = block_on_search
        self.search_calls = 0
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def search(self, request):
        self.search_calls += 1
        if self.search_calls == self.block_on_search:
            self.blocked.set()
            await self.release.wait()
        return await self.delegate.search(request)

    async def traverse_citations(self, request):
        return await self.delegate.traverse_citations(request)

    async def fetch_abstract(self, request):
        return await self.delegate.fetch_abstract(request)


class GatedLLM:
    def __init__(self, responses: list[str], *, block_on_call: int = 1) -> None:
        self.delegate = FixedLLMAdapter(responses)
        self.block_on_call = block_on_call
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096):
        self.calls += 1
        if self.calls == self.block_on_call:
            self.started.set()
            await self.release.wait()
        return await self.delegate.chat_json(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class M3CrashLeaseCheckpointRecoveryContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "paperseek.db"
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.clock = MutableClock()
        migrate_database(self.database)
        self.uow = SQLiteRunUnitOfWork(self.database, clock=self.clock)
        store = FileArtifactStore(self.data_dir)
        self.submission_service = RunSubmissionService(self.uow)
        self.execution_service = RunExecutionService(self.uow, store)
        self.query_service = RunQueryService(self.uow, store)

    async def asyncTearDown(self) -> None:
        self.uow.close()
        self.temp.cleanup()

    def _request(self) -> ResearchWorkflowRequest:
        return ResearchWorkflowRequest(
            question=self.fixture["question"],
            query_budget=QueryLoopBudget(
                target_min=1,
                target_max=50,
                retrieval_pool_min=1,
                query_portfolio_enabled=False,
            ),
            citation_enabled=False,
            fetch_abstracts=False,
        )

    def _create(self, *, deadline_seconds: int = 3600):
        return self.submission_service.create_run(
            self.fixture["question"],
            self.fixture["source"],
            {"fixture_id": self.fixture["fixture_id"]},
            deadline_seconds=deadline_seconds,
        )

    async def _crash_after_retrieval_checkpoint(self) -> tuple[str, TrackingSource]:
        run = self._create()
        source = TrackingSource()
        llm = GatedLLM(self.fixture["llm_responses"], block_on_call=3)

        def resolve(_run, _cancellation):
            return WorkflowExecution(
                llm=llm,
                source=source,
                request=self._request(),
            )

        executor = RunExecutor(
            self.execution_service,
            resolve,
            owner_id="worker-before-crash",
            lease_seconds=30,
            heartbeat_seconds=1,
        )
        task = asyncio.create_task(executor.run_once())
        await asyncio.wait_for(llm.started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        detail = self.query_service.get_run(run.id)
        self.assertEqual(detail.status, RunStatus.RUNNING)
        self.assertEqual(self.execution_service.get_checkpoint(run.id).step_key, "retrieve.fuse")
        return run.id, source

    async def test_expired_lease_is_reclaimed_and_stale_generation_is_fenced(self) -> None:
        run = self._create()
        stale = self.execution_service.claim_next_run("worker-a", lease_seconds=30)
        self.assertEqual(stale.run_id, run.id)
        self.clock.advance(31)

        current = self.execution_service.claim_next_run("worker-b", lease_seconds=30)

        self.assertEqual(current.run_id, run.id)
        self.assertEqual(current.lease_generation, stale.lease_generation + 1)
        self.assertEqual(self.query_service.get_run(run.id).attempt, 2)
        with self.assertRaises(RunOwnershipLost):
            self.uow.append_events_and_checkpoint(
                stale,
                [PendingEvent(event_type="worker.late", stage="executor")],
                None,
                None,
            )

    async def test_cancel_during_configuration_failure_finishes_cancel_not_failed(self) -> None:
        run = self._create()

        def resolve(_run, _cancellation):
            self.submission_service.request_cancel(run.id)
            raise ValueError("The credential became unavailable during cancellation.")

        executor = RunExecutor(self.execution_service, resolve, owner_id="worker")
        result = await executor.run_once()
        self.assertEqual(result.status, RunStatus.CANCELLED)
        self.assertEqual(result.error_code, "")
        self.assertEqual(self.uow.list_events(run.id)[-1].event_type, "run.cancelled")

    async def test_configuration_failure_from_stale_worker_cannot_fail_replacement(self) -> None:
        run = self._create()

        def resolve(_run, _cancellation):
            self.clock.advance(61)
            self.execution_service.claim_next_run("replacement")
            raise ValueError("The old lease cannot load its credentials.")

        executor = RunExecutor(self.execution_service, resolve, owner_id="old")
        result = await executor.run_once()
        self.assertEqual(result.status, RunStatus.RUNNING)
        self.assertEqual(result.lease_owner, "replacement")
        self.assertEqual(result.error_code, "")
        self.assertFalse(any(event.event_type == "run.failed" for event in self.uow.list_events(run.id)))

    async def test_two_workers_competing_for_one_run_have_one_claim_winner(self) -> None:
        run = self._create()
        barrier = threading.Barrier(2)

        def claim(owner: str):
            barrier.wait(timeout=2)
            return self.execution_service.claim_next_run(owner, lease_seconds=30)

        outcomes = await asyncio.gather(
            asyncio.to_thread(claim, "worker-a"),
            asyncio.to_thread(claim, "worker-b"),
            return_exceptions=True,
        )

        self.assertFalse([item for item in outcomes if isinstance(item, Exception)])
        leases = [item for item in outcomes if item is not None]
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases[0].run_id, run.id)
        self.assertEqual(self.query_service.get_run(run.id).attempt, 1)

    async def test_heartbeat_renews_current_lease(self) -> None:
        run = self._create()
        llm = GatedLLM(self.fixture["llm_responses"])

        def resolve(_run, _cancellation):
            source = TrackingSource()
            return WorkflowExecution(llm=llm, source=source, request=self._request())

        executor = RunExecutor(
            self.execution_service,
            resolve,
            owner_id="heartbeat-worker",
            lease_seconds=1,
            heartbeat_seconds=0.02,
        )
        task = asyncio.create_task(executor.run_once())
        await asyncio.wait_for(llm.started.wait(), timeout=2)
        initial_expiry = self.query_service.get_run(run.id).lease_expires_at
        self.clock.advance(0.1)
        await asyncio.sleep(0.08)
        renewed_expiry = self.query_service.get_run(run.id).lease_expires_at
        self.assertGreater(renewed_expiry, initial_expiry)
        llm.release.set()
        detail = await asyncio.wait_for(task, timeout=2)
        self.assertEqual(detail.status, RunStatus.COMPLETED)

    async def test_heartbeat_loss_stops_locally_without_failed_terminal_write(self) -> None:
        run = self._create()
        llm = GatedLLM(self.fixture["llm_responses"])

        def resolve(_run, _cancellation):
            return WorkflowExecution(llm=llm, source=TrackingSource(), request=self._request())

        executor = RunExecutor(
            self.execution_service,
            resolve,
            owner_id="losing-worker",
            lease_seconds=30,
            heartbeat_seconds=0.02,
        )
        with patch.object(
            self.uow,
            "renew_lease",
            side_effect=RunOwnershipLost("controlled lease loss"),
        ):
            detail = await asyncio.wait_for(executor.run_once(), timeout=0.5)

        self.assertEqual(detail.id, run.id)
        self.assertEqual(detail.status, RunStatus.RUNNING)
        self.assertNotIn(
            "run.failed",
            [event.event_type for event in self.query_service.list_events(run.id)],
        )

    async def test_process_rebuild_reclaims_and_resumes_last_complete_stage(self) -> None:
        run_id, crashed_source = await self._crash_after_retrieval_checkpoint()
        self.assertEqual(crashed_source.search_calls, 1)
        self.clock.advance(31)
        self.uow.close()

        rebuilt_uow = SQLiteRunUnitOfWork(self.database, clock=self.clock)
        self.uow = rebuilt_uow
        rebuilt_store = FileArtifactStore(self.data_dir)
        rebuilt_execution = RunExecutionService(rebuilt_uow, rebuilt_store)
        rebuilt_query = RunQueryService(rebuilt_uow, rebuilt_store)
        resumed_source = TrackingSource()

        def resolve(_run, _cancellation):
            return WorkflowExecution(
                llm=FixedLLMAdapter(self.fixture["llm_responses"][2:]),
                source=resumed_source,
                request=self._request(),
            )

        detail = await RunExecutor(
            rebuilt_execution,
            resolve,
            owner_id="worker-after-crash",
            lease_seconds=30,
            heartbeat_seconds=1,
        ).run_once()

        self.assertEqual(detail.id, run_id)
        self.assertEqual(detail.status, RunStatus.COMPLETED)
        self.assertEqual(detail.attempt, 2)
        self.assertEqual(resumed_source.search_calls, 0)
        self.assertIn(
            "query.resumed",
            [event.event_type for event in rebuilt_query.list_events(run_id)],
        )
        recovery_event = next(
            event for event in rebuilt_query.list_events(run_id)
            if event.event_type == "workflow.recovery"
        )
        self.assertEqual(
            recovery_event.payload,
            {"query": 1, "retrieval": 1, "citation": 0, "ranking": 0, "enrichment": 0},
        )
        audit = rebuilt_query.get_run_audit(run_id)
        self.assertEqual(audit.recovery["query"], 1)
        self.assertEqual(audit.recovery["retrieval"], 1)
        self.assertEqual(audit.recovery["total"], 2)

    async def test_incompatible_checkpoint_fails_instead_of_guessing_state(self) -> None:
        run_id, _ = await self._crash_after_retrieval_checkpoint()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE run_checkpoints SET workflow_version = 'unsupported.v0' WHERE run_id = ?",
                (run_id,),
            )
            connection.commit()
        self.clock.advance(31)

        detail = await RunExecutor(
            self.execution_service,
            lambda _run, _cancellation: WorkflowExecution(
                llm=FixedLLMAdapter(self.fixture["llm_responses"][2:]),
                source=TrackingSource(),
                request=self._request(),
            ),
            owner_id="version-worker",
            heartbeat_seconds=1,
        ).run_once()

        self.assertEqual(detail.status, RunStatus.FAILED)
        self.assertEqual(detail.error_code, "incompatible_checkpoint")

    async def test_incompatible_checkpoint_schema_fails_explicitly(self) -> None:
        run_id, _ = await self._crash_after_retrieval_checkpoint()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE run_checkpoints SET schema_version = 99 WHERE run_id = ?",
                (run_id,),
            )
            connection.commit()
        self.clock.advance(31)

        detail = await RunExecutor(
            self.execution_service,
            lambda _run, _cancellation: WorkflowExecution(
                llm=FixedLLMAdapter(self.fixture["llm_responses"][2:]),
                source=TrackingSource(),
                request=self._request(),
            ),
            owner_id="schema-worker",
            heartbeat_seconds=1,
        ).run_once()

        self.assertEqual(detail.status, RunStatus.FAILED)
        self.assertEqual(detail.error_code, "incompatible_checkpoint")

    async def test_three_reclaims_then_recovery_exhaustion_and_deadline_failure(self) -> None:
        run = self._create()
        claims = []
        for index in range(4):
            lease = self.execution_service.claim_next_run(f"worker-{index}", lease_seconds=30)
            claims.append(lease)
            self.assertEqual(lease.run_id, run.id)
            self.clock.advance(31)

        self.assertIsNone(self.execution_service.claim_next_run("worker-exhausted", lease_seconds=30))
        exhausted = self.query_service.get_run(run.id)
        self.assertEqual(exhausted.attempt, 4)
        self.assertEqual(exhausted.status, RunStatus.FAILED)
        self.assertEqual(exhausted.error_code, "executor_recovery_exhausted")

        deadline_run = self._create(deadline_seconds=10)
        self.assertEqual(deadline_run.deadline_at, self.clock() + timedelta(seconds=10))
        self.clock.advance(11)
        self.assertIsNone(self.execution_service.claim_next_run("deadline-worker", lease_seconds=30))
        deadline = self.query_service.get_run(deadline_run.id)
        self.assertEqual(deadline.status, RunStatus.FAILED)
        self.assertEqual(deadline.error_code, "run_deadline_exceeded")


if __name__ == "__main__":
    unittest.main()
