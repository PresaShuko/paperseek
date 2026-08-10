"""Bounded abstract enrichment with explicit partial-failure semantics."""

from __future__ import annotations

import asyncio
import hashlib
import json

from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.models import (
    AbstractEnrichmentRequest,
    AbstractEnrichmentResult,
    AbstractEnrichmentResumeState,
    AbstractFetchRequest,
    AbstractFetchResult,
    CheckpointDraft,
    CoreProgressEvent,
    RankedPaper,
)
from paperseek_core.ports import AbstractPort, CancellationToken, WorkflowObserver


class AbstractEnrichmentPipeline:
    def __init__(
        self,
        source: AbstractPort,
        observer: WorkflowObserver,
        *,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.source = source
        self.observer = observer
        self.cancellation = cancellation

    async def run(self, request: AbstractEnrichmentRequest) -> AbstractEnrichmentResult:
        self.cancellation.raise_if_cancelled()
        items = list(request.items)
        resume = request.resume or AbstractEnrichmentResumeState()
        completed = list(resume.completed_ids)
        completed_set = set(completed)
        abstract_by_uid = dict(resume.abstract_by_uid)
        warnings = list(resume.warnings)
        items = self._apply_abstracts(items, abstract_by_uid)
        if not request.enabled or not items:
            return self._result(items, completed, abstract_by_uid, warnings)

        pending = [
            item
            for item in items
            if item.document.uid not in completed_set
            and item.document.identifiers is not None
            and item.document.identifiers.doi.strip()
        ]
        if not pending:
            return self._result(items, completed, abstract_by_uid, warnings)

        self._event(
            "enrichment.started",
            {
                "candidate_count": len(items),
                "request_count": len(pending),
                "batch_size": request.batch_size,
                "concurrency": request.concurrency,
            },
        )
        for start in range(0, len(pending), request.batch_size):
            self.cancellation.raise_if_cancelled()
            batch = pending[start:start + request.batch_size]
            outcomes = await self._fetch_batch(batch, request.concurrency)
            for item, outcome in zip(batch, outcomes):
                uid = item.document.uid
                doi = item.document.identifiers.doi.strip() if item.document.identifiers else ""
                completed.append(uid)
                completed_set.add(uid)
                if isinstance(outcome, Exception):
                    warning = f"abstract_enrichment_failed:{doi}"
                    warnings.append(warning)
                    self._event(
                        "enrichment.degraded",
                        {
                            "code": "abstract_enrichment_failed",
                            "uid": uid,
                            "error_type": type(outcome).__name__,
                        },
                    )
                elif outcome.found and outcome.abstract:
                    abstract_by_uid[uid] = outcome.abstract
                else:
                    warning = f"abstract_enrichment_unavailable:{doi}"
                    warnings.append(warning)
                    self._event(
                        "enrichment.degraded",
                        {"code": "abstract_enrichment_unavailable", "uid": uid},
                    )
            items = self._apply_abstracts(items, abstract_by_uid)
            warnings = list(dict.fromkeys(warnings))
            self._checkpoint(items, completed, abstract_by_uid, warnings)
            self._event(
                "enrichment.progress",
                {
                    "completed_count": len(completed),
                    "request_count": len(pending),
                    "warning_count": len(warnings),
                },
            )
        self._event(
            "enrichment.completed",
            {
                "candidate_count": len(items),
                "enriched_count": len(abstract_by_uid),
                "warning_count": len(warnings),
            },
        )
        return self._result(items, completed, abstract_by_uid, warnings)

    async def _fetch_batch(
        self,
        batch: list[RankedPaper],
        concurrency: int,
    ) -> list[AbstractFetchResult | Exception]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def fetch(item: RankedPaper) -> AbstractFetchResult | Exception:
            doi = item.document.identifiers.doi.strip() if item.document.identifiers else ""
            try:
                async with semaphore:
                    self.cancellation.raise_if_cancelled()
                    result = await self.source.fetch_abstract(AbstractFetchRequest(doi=doi))
                    self.cancellation.raise_if_cancelled()
                    return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return exc

        tasks: list[asyncio.Task[AbstractFetchResult | Exception]] = []
        async with asyncio.TaskGroup() as group:
            for item in batch:
                self.cancellation.raise_if_cancelled()
                tasks.append(group.create_task(fetch(item)))
        return [task.result() for task in tasks]

    @staticmethod
    def _apply_abstracts(
        items: list[RankedPaper],
        abstract_by_uid: dict[str, str],
    ) -> list[RankedPaper]:
        output = []
        for item in items:
            abstract = abstract_by_uid.get(item.document.uid)
            if not abstract:
                output.append(item)
                continue
            output.append(
                item.model_copy(
                    update={
                        "document": item.document.model_copy(update={"abstract": abstract})
                    }
                )
            )
        return output

    def _checkpoint(
        self,
        items: list[RankedPaper],
        completed: list[str],
        abstract_by_uid: dict[str, str],
        warnings: list[str],
    ) -> None:
        self.cancellation.raise_if_cancelled()
        payload = {
            "completed_ids": completed,
            "abstract_by_uid": abstract_by_uid,
            "warnings": warnings,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key="enrich_results.batch",
                idempotency_key=f"enrichment:{digest}",
                state={
                    **payload,
                    "items": [item.model_dump(mode="json") for item in items],
                    "resume_from_stage": "enrich_results",
                },
                workflow_version="m2.enrichment.v1",
            )
        )

    @staticmethod
    def _result(
        items: list[RankedPaper],
        completed: list[str],
        abstract_by_uid: dict[str, str],
        warnings: list[str],
    ) -> AbstractEnrichmentResult:
        resume = AbstractEnrichmentResumeState(
            completed_ids=list(completed),
            abstract_by_uid=dict(abstract_by_uid),
            warnings=list(warnings),
        )
        return AbstractEnrichmentResult(
            items=items,
            warnings=warnings,
            completed_ids=completed,
            resume=resume,
        )

    def _event(self, event_type: str, payload: dict) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="enrichment", payload=payload)
        )


__all__ = ["AbstractEnrichmentPipeline"]
