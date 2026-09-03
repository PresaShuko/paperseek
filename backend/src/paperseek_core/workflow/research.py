"""The single M2 research workflow over explicit core ports."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from paperseek_core.citation import CitationPipeline
from paperseek_core.enrichment import AbstractEnrichmentPipeline
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.final_result import FinalResultAssembler
from paperseek_core.models import (
    AbstractEnrichmentRequest,
    CheckpointDraft,
    CitationExpansionRequest,
    CoreProgressEvent,
    QueryLoopRequest,
    RankingRequest,
    ResearchAssemblyRequest,
    ResearchResult,
    ResearchWorkflowRequest,
    ResearchWorkflowResumeState,
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
from paperseek_core.query_loop import QueryLoopPipeline
from paperseek_core.document_identity import document_key
from paperseek_core.ranking import RankingPipeline
from paperseek_core.retrieval import RetrievalPipeline


class ResearchWorkflow:
    def __init__(
        self,
        *,
        llm: LLMPort,
        source: SourcePort,
        observer: WorkflowObserver,
        abstracts: AbstractPort | None = None,
        candidate_metadata: CandidateMetadataPort | None = None,
        embedding: EmbeddingPort | None = None,
        reranker: RerankPort | None = None,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.llm = llm
        self.source = source
        self.observer = observer
        self.abstracts = abstracts
        self.candidate_metadata = candidate_metadata
        self.embedding = embedding
        self.reranker = reranker
        self.cancellation = cancellation

    async def run(self, request: ResearchWorkflowRequest) -> ResearchResult:
        resume = request.resume or ResearchWorkflowResumeState()
        self._event(
            "workflow.started",
            {"source": self.source.name, "question_length": len(request.question)},
        )
        recovery = {
            "query": int(resume.query is not None),
            "retrieval": int(
                resume.retrieval is not None
                or bool(resume.retrieval_completed_lanes)
                or bool(resume.retrieval_lane_results)
            ),
            "citation": int(resume.citation is not None),
            "ranking": int(bool(resume.ranking_scores) or bool(resume.ranking_completed_batch_ids)),
            "enrichment": int(resume.enrichment is not None),
        }
        if any(recovery.values()):
            self._event("workflow.recovery", recovery)
        query = await QueryLoopPipeline(
            self.llm,
            self.source,
            self.observer,
            cancellation=self.cancellation,
        ).run(
            request=self._query_request(request, resume)
        )
        self.cancellation.raise_if_cancelled()
        if resume.retrieval is not None:
            retrieval = resume.retrieval
        else:
            retrieval_request = query.retrieval_request.model_copy(
                update={
                    "resume_lane_results": resume.retrieval_lane_results,
                    "completed_lanes": resume.retrieval_completed_lanes,
                    "crossref_metadata_enrichment": request.crossref_metadata_enrichment,
                }
            )
            retrieval = await RetrievalPipeline(
                self.source,
                self.observer,
                candidate_metadata=self.candidate_metadata,
                embedding=self.embedding,
                reranker=self.reranker,
                cancellation=self.cancellation,
            ).run(retrieval_request)
        self.cancellation.raise_if_cancelled()
        if resume.citation is not None:
            citation = resume.citation
        else:
            citation = await CitationPipeline(
                self.source,
                self.observer,
                cancellation=self.cancellation,
            ).run(
                CitationExpansionRequest(
                    candidates=retrieval.documents,
                    seed_candidates=retrieval.documents,
                    enabled=request.citation_enabled,
                    seed_count=request.citation_seed_count,
                    per_seed=request.citation_per_seed,
                    max_records=request.citation_max_records,
                    depth=request.citation_depth,
                    field_ids=request.query_budget.field_ids,
                )
            )
        provenance = self._merge_provenance(
            citation.candidates,
            retrieval.provenance_by_identity,
            citation.provenance_by_identity,
        )
        self.cancellation.raise_if_cancelled()
        ranking = await RankingPipeline(
            self.llm,
            self.observer,
            cancellation=self.cancellation,
        ).run(
            RankingRequest(
                question=request.question,
                documents=citation.candidates[: request.query_budget.ranking_candidate_limit],
                plan_context=query.search_plan.audit_summary(),
                provenance_by_identity=provenance,
                batch_size=request.ranking_batch_size,
                concurrency=request.ranking_concurrency,
                resume_scores=resume.ranking_scores,
                completed_batch_ids=resume.ranking_completed_batch_ids,
            )
        )
        enriched_items = list(ranking.items)
        enrichment_warnings: list[str] = []
        if request.fetch_abstracts and enriched_items:
            abstract_port = self.abstracts
            if abstract_port is None and isinstance(self.source, AbstractPort):
                abstract_port = self.source
            if abstract_port is None:
                enrichment_warnings = ["abstract_enrichment_unsupported"]
                self.observer.on_event(
                    CoreProgressEvent(
                        event_type="enrichment.skipped",
                        stage="enrichment",
                        payload={"code": "abstract_enrichment_unsupported"},
                    )
                )
            else:
                enrichment = await AbstractEnrichmentPipeline(
                    abstract_port,
                    self.observer,
                    cancellation=self.cancellation,
                ).run(
                    AbstractEnrichmentRequest(
                        items=enriched_items,
                        batch_size=request.enrichment_batch_size,
                        concurrency=request.enrichment_concurrency,
                        resume=resume.enrichment,
                    )
                )
                enriched_items = enrichment.items
                enrichment_warnings = enrichment.warnings

        warnings = list(
            dict.fromkeys(
                [
                    *query.warnings,
                    *retrieval.warnings,
                    *citation.warnings,
                    *ranking.warnings,
                    *enrichment_warnings,
                ]
            )
        )
        result = FinalResultAssembler().assemble(
            ResearchAssemblyRequest(
                question=request.question,
                source=self.source.name,
                search_plan=query.search_plan,
                final_query=query.final_query,
                total=query.total,
                iterations=query.iterations,
                history=query.history,
                query_view_selection=query.query_view_selection,
                query_portfolio=query.query_portfolio,
                query_iteration_memory=[
                    {
                        "iteration": item.iteration,
                        "query": item.query,
                        "total": item.total,
                        "candidate_count": len(item.records),
                    }
                    for item in query.query_iteration_memory
                ],
                citation_map=citation.citation_map,
                ranking_steps=self._ranking_steps(retrieval, citation, ranking),
                search_state=self._search_state(query, citation.candidates, provenance),
                items=enriched_items,
                warnings=warnings,
            )
        )
        self.cancellation.raise_if_cancelled()
        self._final_checkpoint(result)
        self._event(
            "workflow.completed",
            {
                "source": self.source.name,
                "result_count": len(result.ranked),
                "warning_count": len(result.warnings),
                "artifact_count": len(result.artifacts),
            },
        )
        return result

    @staticmethod
    def _query_request(
        request: ResearchWorkflowRequest,
        resume: ResearchWorkflowResumeState,
    ) -> QueryLoopRequest:
        return QueryLoopRequest(
            question=request.question,
            source_context=request.source_context,
            budget=request.query_budget,
            resume=resume.query,
        )

    @staticmethod
    def _merge_provenance(
        candidates,
        retrieval: dict[str, dict[str, Any]],
        citation: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        output = {key: dict(value) for key, value in retrieval.items()}
        for index, document in enumerate(candidates, 1):
            key = document_key(document)
            current = dict(output.get(key) or output.get(document.uid) or {})
            citation_detail = citation.get(key) or citation.get(document.uid) or {}
            if citation_detail:
                current.update(citation_detail)
                current.setdefault("origins", ["citation_expansion"])
                current.setdefault("retrieval_lanes", ["citation_expansion"])
                current.setdefault("retrieval_score", 0.0)
                current.setdefault("source_rank", index)
            output[key] = current
            output[document.uid] = current
        return output

    @staticmethod
    def _ranking_steps(retrieval, citation, ranking) -> list[dict[str, Any]]:
        return [
            {
                "id": "multi_lane_retrieval",
                "title": "Multi-lane retrieval",
                "status": "complete",
                "current": len(retrieval.documents),
                "total": len(retrieval.documents),
                "candidate_count": len(retrieval.documents),
                "lane_counts": retrieval.lane_counts,
            },
            {
                "id": "citation_expansion",
                "title": "Citation expansion",
                "status": citation.citation_map.get("status", "complete"),
                "current": len(citation.candidates),
                "total": len(citation.candidates),
                "candidate_count": len(citation.candidates),
                "added_candidates": int(citation.citation_map.get("added_candidates") or 0),
            },
            {
                "id": "llm_reranking",
                "title": "LLM reranking",
                "status": "complete" if not ranking.warnings else "degraded",
                "current": len(ranking.items),
                "total": len(ranking.items),
                "candidate_count": len(ranking.items),
            },
        ]

    @staticmethod
    def _search_state(query, candidates, provenance) -> dict[str, Any]:
        keys = [document_key(document) for document in candidates]
        ledger = {}
        for document in candidates:
            key = document_key(document)
            detail = dict(provenance.get(key) or provenance.get(document.uid) or {})
            identifiers = document.identifiers
            ledger[key] = {
                "candidate_id": key,
                "title": document.title,
                "doi": identifiers.doi if identifiers else "",
                "openalex": identifiers.openalex if identifiers else "",
                "year": document.source.publish_year if document.source else None,
                "sources": detail.get("sources") or ([document.provider] if document.provider else []),
                "origins": detail.get("origins") or [],
                "retrieval_lanes": detail.get("retrieval_lanes") or [],
                "retrieval_score": float(detail.get("retrieval_score") or 0),
            }
        origin_counts: dict[str, int] = {}
        for detail in ledger.values():
            for origin in detail["origins"]:
                origin_counts[origin] = origin_counts.get(origin, 0) + 1
        return {
            "question": query.question,
            "source": query.source,
            "current_query": query.final_query,
            "terminal_status": query.terminal_status,
            "candidate_queue": {
                "keys": keys,
                "ledger": ledger,
                "origin_counts": origin_counts,
                "duplicate_count": 0,
                "ledger_summary": {
                    "total_candidates": len(keys),
                    "serialized_candidates": len(keys),
                    "omitted_candidates": 0,
                },
            },
        }

    def _final_checkpoint(self, result: ResearchResult) -> None:
        self.cancellation.raise_if_cancelled()
        artifact_rows = [
            {
                "kind": artifact.kind,
                "filename": artifact.filename,
                "media_type": artifact.media_type,
                "size": len(artifact.content.encode("utf-8")),
                "sha256": hashlib.sha256(artifact.content.encode("utf-8")).hexdigest(),
            }
            for artifact in result.artifacts
        ]
        payload = {
            "final_result": result.public_payload(),
            "warnings": result.warnings,
            "artifacts": artifact_rows,
            "resume_from_stage": "complete",
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key="assemble_final_result",
                idempotency_key=f"final:{digest}",
                state=payload,
                workflow_version="m2.research-workflow.v1",
            )
        )

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="workflow", payload=payload)
        )


__all__ = ["ResearchWorkflow"]
