from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import json

from pydantic import ValidationError

from paperseek_app.errors import (
    ArtifactError,
    IncompatibleCheckpoint,
    RunOwnershipLost,
    RunPersistenceError,
    RunStateError,
)
from paperseek_app.execution import CancellationScope, WorkflowExecution
from paperseek_app.models import (
    ArtifactRole,
    ArtifactVisibility,
    ArtifactWrite,
    LeaseToken,
    PendingEvent,
    PersistedCheckpoint,
    RunDetail,
    RunStatus,
    StoredArtifact,
)
from paperseek_app.ports import ArtifactStore, RunUnitOfWork
from paperseek_core.errors import LLMRequestError, QueryGenerationError, QuerySourceError, RetrievalSourceError
from paperseek_core.models import (
    AbstractEnrichmentResumeState,
    CheckpointDraft,
    CitationExpansionResult,
    CoreProgressEvent,
    PaperRecord,
    QueryLoopResumeState,
    ResearchWorkflowRequest,
    ResearchWorkflowResumeState,
    RetrievalResult,
)
from paperseek_core.ports import (
    AbstractPort,
    CandidateMetadataPort,
    CancellationToken,
    EmbeddingPort,
    LLMPort,
    RerankPort,
    SourcePort,
    WorkflowObserver,
)


class TransactionalObserver:
    def __init__(
        self,
        service: RunExecutionService,
        lease: LeaseToken,
        workflow_version: str,
    ) -> None:
        self._service = service
        self._lease = lease
        self._workflow_version = workflow_version
        self._pending: list[PendingEvent] = []

    def on_event(self, event: CoreProgressEvent) -> None:
        self._pending.append(
            PendingEvent(
                event_type=event.event_type,
                stage=event.stage,
                payload=event.payload,
                schema_version=event.schema_version,
            )
        )

    def on_checkpoint(self, checkpoint: CheckpointDraft) -> None:
        state = {
            **checkpoint.state,
            "step_workflow_version": checkpoint.workflow_version,
        }
        self._service.append_checkpoint(
            self._lease,
            self.drain(),
            checkpoint.model_copy(
                update={
                    "state": state,
                    "workflow_version": self._workflow_version,
                }
            ),
        )

    def drain(self) -> list[PendingEvent]:
        pending, self._pending = self._pending, []
        return pending


class RunExecutionService:
    _CHECKPOINT_SCHEMA_VERSION = 1
    _STEP_VERSIONS = {
        "query.": "m2.query-loop.v1",
        "retrieve.": "m2.retrieval.v1",
        "expand_citations": "m2.citation.v1",
        "rank_results.": "m2.ranking.v1",
        "enrich_results.": "m2.enrichment.v1",
        "assemble_final_result": "m2.research-workflow.v1",
    }

    def __init__(self, uow: RunUnitOfWork, artifact_store: ArtifactStore) -> None:
        self.uow = uow
        self.artifact_store = artifact_store

    def claim_next_run(self, owner_id: str, lease_seconds: int = 60) -> LeaseToken | None:
        return self.uow.claim_next_run(owner_id, timedelta(seconds=lease_seconds))

    def get_run(self, run_id: str) -> RunDetail:
        return self.uow.get_run(run_id)

    def get_checkpoint(self, run_id: str) -> PersistedCheckpoint | None:
        checkpoint = self.uow.get_checkpoint(run_id)
        return None if checkpoint is None else self._hydrate_checkpoint(checkpoint)

    def list_checkpoints(self, run_id: str) -> list[PersistedCheckpoint]:
        return [
            self._hydrate_checkpoint(checkpoint)
            for checkpoint in self.uow.list_checkpoints(run_id)
        ]

    def complete_cancel(self, lease: LeaseToken) -> RunDetail:
        return self.uow.complete_cancel(lease)

    def fail_claimed_run(self, lease: LeaseToken, error_code: str) -> RunDetail:
        cancelled = self._finish_cancel_if_requested(lease, CancellationScope())
        if cancelled is not None:
            return cancelled
        return self.uow.fail_run(lease, [], error_code)

    async def execute_claimed_workflow(
        self,
        lease: LeaseToken,
        *,
        llm: LLMPort,
        source: SourcePort,
        request: ResearchWorkflowRequest,
        abstracts: AbstractPort | None = None,
        candidate_metadata: CandidateMetadataPort | None = None,
        embedding: EmbeddingPort | None = None,
        reranker: RerankPort | None = None,
        cancellation: CancellationScope | None = None,
        cancellation_poll_seconds: float = 0.05,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 20.0,
    ) -> RunDetail:
        run = self.uow.get_run(lease.run_id)
        try:
            resume = self._resume_state(run)
        except IncompatibleCheckpoint:
            return self.uow.fail_run(lease, [], "incompatible_checkpoint")
        observer = TransactionalObserver(self, lease, run.versions.workflow_version)
        scope = cancellation or CancellationScope()
        try:
            result = await self._run_cancellable_workflow(
                lease,
                WorkflowExecution(
                    llm=llm,
                    source=source,
                    request=request.model_copy(update={"resume": resume}),
                    abstracts=abstracts,
                    candidate_metadata=candidate_metadata,
                    embedding=embedding,
                    reranker=reranker,
                ),
                observer,
                scope,
                cancellation_poll_seconds,
                lease_seconds,
                heartbeat_seconds,
            )
        except asyncio.CancelledError:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            raise
        except RunOwnershipLost:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            raise
        except (LLMRequestError, QueryGenerationError, QuerySourceError, RetrievalSourceError) as exc:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            code = exc.code if isinstance(exc, LLMRequestError) else "research_workflow_failed"
            return self.uow.fail_run(lease, observer.drain(), code)
        except ArtifactError:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            return self.uow.fail_run(lease, observer.drain(), "artifact_persistence_failed")
        except RunPersistenceError:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            return self.uow.fail_run(lease, observer.drain(), "checkpoint_commit_failed")

        cancelled = self._finish_cancel_if_requested(lease, scope)
        if cancelled is not None:
            return cancelled
        try:
            artifacts = self._persist_required_artifacts(lease, run, result, scope)
        except ArtifactError:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            return self.uow.fail_run(lease, observer.drain(), "artifact_persistence_failed")
        cancelled = self._finish_cancel_if_requested(lease, scope)
        if cancelled is not None:
            return cancelled
        try:
            return self.uow.complete_run(lease, observer.drain(), result, artifacts)
        except RunOwnershipLost:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            raise
        except RunPersistenceError:
            cancelled = self._finish_cancel_if_requested(lease, scope)
            if cancelled is not None:
                return cancelled
            return self.uow.fail_run(lease, observer.drain(), "artifact_commit_failed")

    async def _run_cancellable_workflow(
        self,
        lease: LeaseToken,
        execution: WorkflowExecution,
        observer: WorkflowObserver,
        scope: CancellationScope,
        poll_seconds: float,
        lease_seconds: int,
        heartbeat_seconds: float,
    ):
        workflow_task = asyncio.create_task(execution.run(observer, scope))

        async def monitor() -> None:
            while True:
                status = self.uow.get_run(lease.run_id).status
                if status in {RunStatus.CANCELLING, RunStatus.CANCELLED}:
                    scope.cancel()
                    return
                await asyncio.sleep(max(0.01, poll_seconds))

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(max(0.01, heartbeat_seconds))
                try:
                    self.uow.renew_lease(lease, timedelta(seconds=lease_seconds))
                except (RunOwnershipLost, RunStateError, RunPersistenceError) as exc:
                    scope.cancel()
                    raise RunOwnershipLost("The executor lost its run lease during renewal.") from exc

        monitor_task = asyncio.create_task(monitor())
        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait(
                {workflow_task, monitor_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if monitor_task in done:
                await monitor_task
                if scope.cancelled:
                    workflow_task.cancel()
                    await asyncio.gather(workflow_task, return_exceptions=True)
                    raise asyncio.CancelledError
            if heartbeat_task in done:
                workflow_task.cancel()
                await asyncio.gather(workflow_task, return_exceptions=True)
                await heartbeat_task
            return await workflow_task
        finally:
            monitor_task.cancel()
            heartbeat_task.cancel()
            if not workflow_task.done():
                workflow_task.cancel()
            await asyncio.gather(
                monitor_task,
                heartbeat_task,
                workflow_task,
                return_exceptions=True,
            )

    def _finish_cancel_if_requested(
        self,
        lease: LeaseToken,
        cancellation: CancellationScope,
    ) -> RunDetail | None:
        detail = self.uow.get_run(lease.run_id)
        if detail.status is RunStatus.CANCELLING:
            cancellation.cancel()
            return self.uow.complete_cancel(lease)
        if detail.status is RunStatus.CANCELLED:
            cancellation.cancel()
            return detail
        return None

    def append_checkpoint(
        self,
        lease: LeaseToken,
        events: list[PendingEvent],
        checkpoint: CheckpointDraft,
    ) -> PersistedCheckpoint:
        content = json.dumps(
            checkpoint.state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        name_digest = hashlib.sha256(checkpoint.idempotency_key.encode("utf-8")).hexdigest()
        artifact = self.artifact_store.put(
            ArtifactWrite(
                run_id=lease.run_id,
                kind="checkpoint",
                role=ArtifactRole.RECOVERY,
                visibility=ArtifactVisibility.INTERNAL,
                filename=f"state-{name_digest}.json",
                media_type="application/json",
                schema_version=checkpoint.schema_version,
                content=content,
            )
        )
        persisted = self.uow.append_events_and_checkpoint(
            lease,
            events,
            checkpoint,
            artifact,
        )
        if persisted is None:
            raise RunPersistenceError("The checkpoint was not committed.")
        return persisted

    def _hydrate_checkpoint(self, checkpoint: PersistedCheckpoint) -> PersistedCheckpoint:
        if not checkpoint.state_artifact_id:
            return checkpoint
        artifact = self.uow.get_artifact(checkpoint.state_artifact_id)
        try:
            state = json.loads(self.artifact_store.read(artifact))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RunPersistenceError("The checkpoint artifact is not valid JSON.") from exc
        if not isinstance(state, dict):
            raise RunPersistenceError("The checkpoint artifact must contain an object.")
        return checkpoint.model_copy(update={"state": state})

    def _resume_state(self, run: RunDetail) -> ResearchWorkflowResumeState | None:
        persisted = self.uow.list_checkpoints(run.id)
        if not persisted:
            return None
        for checkpoint in persisted:
            self._validate_checkpoint_metadata(run, checkpoint)
        checkpoints = [self._hydrate_checkpoint(item) for item in persisted]
        try:
            return self._compose_resume_state(checkpoints)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise IncompatibleCheckpoint("Checkpoint state is incompatible with this executor.") from exc

    def _validate_checkpoint_metadata(
        self,
        run: RunDetail,
        checkpoint: PersistedCheckpoint,
    ) -> None:
        if (
            checkpoint.workflow_version != run.versions.workflow_version
            or checkpoint.schema_version != self._CHECKPOINT_SCHEMA_VERSION
            or not checkpoint.state_artifact_id
        ):
            raise IncompatibleCheckpoint("Checkpoint metadata is incompatible with this executor.")

    def _compose_resume_state(
        self,
        checkpoints: list[PersistedCheckpoint],
    ) -> ResearchWorkflowResumeState:
        query = None
        retrieval = None
        retrieval_lane_results: dict[str, list[PaperRecord]] = {}
        retrieval_completed_lanes: list[str] = []
        citation = None
        ranking_scores = []
        ranking_completed_batch_ids: list[str] = []
        enrichment = None
        for checkpoint in checkpoints:
            state = dict(checkpoint.state)
            step_version = str(state.pop("step_workflow_version", ""))
            if step_version != self._expected_step_version(checkpoint.step_key):
                raise IncompatibleCheckpoint("Checkpoint step version is incompatible.")
            if checkpoint.step_key.startswith("query."):
                query = QueryLoopResumeState.model_validate(state)
            elif checkpoint.step_key == "retrieve.lane":
                retrieval_lane_results = {
                    lane: [PaperRecord.model_validate(item) for item in records]
                    for lane, records in dict(state.get("lane_results") or {}).items()
                }
                retrieval_completed_lanes = list(state.get("completed_lanes") or [])
            elif checkpoint.step_key == "retrieve.fuse":
                retrieval = RetrievalResult(
                    documents=[
                        PaperRecord.model_validate(item)
                        for item in state.get("candidate_pool") or []
                    ],
                    provenance_by_identity=dict(state.get("provenance_by_identity") or {}),
                    lane_counts=dict(state.get("lane_counts") or {}),
                    total_candidates=int(state.get("total_candidates") or 0),
                    completed_lanes=list(state.get("completed_lanes") or []),
                    warnings=list(state.get("warnings") or []),
                )
            elif checkpoint.step_key == "expand_citations":
                if "candidates" not in state or "provenance_by_identity" not in state:
                    raise IncompatibleCheckpoint("Citation checkpoint lacks recovery state.")
                citation = CitationExpansionResult(
                    candidates=[
                        PaperRecord.model_validate(item)
                        for item in state.get("candidates") or []
                    ],
                    citation_map=dict(state.get("citation_map") or {}),
                    provenance_by_identity=dict(state.get("provenance_by_identity") or {}),
                    warnings=list(state.get("warnings") or []),
                )
            elif checkpoint.step_key == "rank_results.batch":
                ranking_scores = list(state.get("ranking_scores") or [])
                ranking_completed_batch_ids = list(state.get("completed_batch_ids") or [])
            elif checkpoint.step_key == "enrich_results.batch":
                enrichment = AbstractEnrichmentResumeState(
                    completed_ids=list(state.get("completed_ids") or []),
                    abstract_by_uid=dict(state.get("abstract_by_uid") or {}),
                    warnings=list(state.get("warnings") or []),
                )
        return ResearchWorkflowResumeState(
            query=query,
            retrieval=retrieval,
            retrieval_lane_results=retrieval_lane_results,
            retrieval_completed_lanes=retrieval_completed_lanes,
            citation=citation,
            ranking_scores=ranking_scores,
            ranking_completed_batch_ids=ranking_completed_batch_ids,
            enrichment=enrichment,
        )

    def _expected_step_version(self, step_key: str) -> str:
        for prefix, version in self._STEP_VERSIONS.items():
            if step_key == prefix or step_key.startswith(prefix):
                return version
        raise IncompatibleCheckpoint("Checkpoint step is not supported by this executor.")

    def _persist_required_artifacts(
        self,
        lease: LeaseToken,
        run: RunDetail,
        result,
        cancellation: CancellationToken,
    ) -> list[StoredArtifact]:
        artifacts = []
        for draft in result.artifacts:
            cancellation.raise_if_cancelled()
            current = self.uow.get_run(lease.run_id)
            if (
                current.status is not RunStatus.RUNNING
                or current.lease_owner != lease.owner_id
                or current.lease_generation != lease.lease_generation
            ):
                raise RunOwnershipLost("The run can no longer accept required artifacts.")
            artifacts.append(
                self.artifact_store.put(
                    ArtifactWrite(
                        run_id=lease.run_id,
                        kind=draft.kind,
                        role=ArtifactRole.COMPLETION_REQUIRED,
                        visibility=ArtifactVisibility.USER,
                        filename=draft.filename,
                        media_type=draft.media_type,
                        schema_version=run.versions.artifact_schema_version,
                        content=draft.content.encode("utf-8"),
                    )
                )
            )
        return artifacts
