from __future__ import annotations

from typing import Any

from paperseek_core.checkpoints import paper_records_from_checkpoint
from paperseek_core.harness import SearchCheckpoint


class SearchCompletionPipeline:
    """Run retrieval, citation expansion, ranking, and final result assembly."""

    def __init__(self, host: Any):
        self.host = host

    def run(
        self,
        question: str,
        query: str,
        total: int,
        hits: list,
        history: list,
        iteration: int,
        checkpoint: Optional[SearchCheckpoint] = None,
    ) -> dict:
        host = self.host
        checkpoint_records = paper_records_from_checkpoint(checkpoint.records) if checkpoint else []
        checkpoint_stage = checkpoint.stage if checkpoint else ""
        resume_stage = str((checkpoint.metadata or {}).get("resume_from_stage") or checkpoint_stage) if checkpoint else ""
        checkpoint_step = str((checkpoint.metadata or {}).get("step_id") or "") if checkpoint else ""
        if checkpoint_stage == "ranking_batch" and checkpoint_step == "llm_reranking":
            resume_stage = "ranking_batch"

        if checkpoint:
            host._emit_log(
                f"Resuming search from durable checkpoint: stage={checkpoint_stage}; "
                f"resume_stage={resume_stage}; sequence={checkpoint.sequence}."
            )

        host.ranking_steps = dict(host.ranking_steps or {})
        ranking_context = {
            "source": host.data_source,
            "total": total,
            "history": history,
            "final_query": query,
            "preview": host._preview_hits(hits),
        }
        host.ranking_context = dict(ranking_context)
        host._check_cancelled()
        host._emit_stage("ranking", "processing", candidate_count=len(hits or []), **ranking_context)
        if resume_stage in {"candidate_merge", "candidate_feedback", "citation_layer", "pre_rank", "ranking_batch", "ranking_complete"}:
            retrieved = checkpoint_records
        elif total == 0 and not hits:
            retrieved = []
        else:
            retrieved = host._retrieve_candidates(question, query, hits)
            host._save_checkpoint(
                "candidate_merge",
                records=retrieved,
                metadata={"resume_from_stage": "candidate_merge"},
            )
        host._check_cancelled()
        if resume_stage in {"citation_layer", "pre_rank", "ranking_batch", "ranking_complete"}:
            candidates = checkpoint_records
        elif resume_stage == "candidate_feedback":
            host._emit_log("Resuming candidate preparation from its durable checkpoint.")
            candidates = host._prepare_candidates(question, retrieved)
            host._save_checkpoint(
                "citation_layer",
                records=candidates,
                metadata={"resume_from_stage": "citation_layer"},
            )
        else:
            host._emit_ranking_step(
                "candidate_preparation",
                "processing",
                "Preparing LLM candidate list",
                current=0,
                total=max(1, len(retrieved or [])),
                detail=f"{len(retrieved or [])} fused candidates before citation expansion.",
            )
            candidates = host._prepare_candidates(question, retrieved)
            host._emit_ranking_step(
                "candidate_preparation",
                "complete",
                "Preparing LLM candidate list",
                current=len(candidates),
                total=max(1, len(candidates)),
                detail=f"{len(candidates)} candidates ready before LLM ranking.",
                candidate_count=len(candidates),
            )
            host._save_checkpoint(
                "citation_layer",
                records=candidates,
                metadata={"resume_from_stage": "citation_layer"},
            )

        ranking_candidate_limit = host._llm_ranking_candidate_limit()
        if resume_stage in {"pre_rank", "ranking_batch", "ranking_complete"}:
            all_candidates = list(candidates)
        else:
            all_candidates = list(candidates)
            if len(candidates) > ranking_candidate_limit:
                host._emit_log(
                    f"LLM ranking candidate list truncated: candidates={len(candidates)}; "
                    f"ranking_candidate_limit={ranking_candidate_limit}."
                )
                candidates = candidates[:ranking_candidate_limit]
            host._record_candidate_gate(all_candidates, candidates, ranking_candidate_limit)
            host._save_checkpoint(
                "pre_rank",
                records=candidates,
                metadata={"resume_from_stage": "pre_rank", "all_candidate_count": len(all_candidates)},
            )
        if len(candidates) != len(hits or []):
            host._emit_stage("ranking", "processing", candidate_count=len(candidates), **ranking_context)
        host._check_cancelled()
        if resume_stage == "ranking_complete":
            ranked_all = host._rank_from_scores(candidates, checkpoint.ranking_scores)
        else:
            ranked_all = host._rank_results(
                question,
                candidates,
                ranking_context=ranking_context,
                resume_scores=(checkpoint.ranking_scores if resume_stage == "ranking_batch" else None),
                completed_batch_ids=(checkpoint.completed_batch_ids if resume_stage == "ranking_batch" else None),
                checkpoint_records=candidates,
                checkpoint_resume_stage="pre_rank",
            )
            host._save_checkpoint(
                "ranking_complete",
                records=candidates,
                ranking_scores=host._ranking_scores_from_ranked(ranked_all),
                metadata={"resume_from_stage": "ranking_complete"},
            )
        host._record_candidate_scores(ranked_all, "llm_scored")
        ranked = host._select_ranked_output(ranked_all)
        host._record_final_candidates(ranked)
        host._finalize_citation_map(ranked)

        if host.config.fetch_abstracts:
            host._check_cancelled()
            host._emit_log("External abstract enrichment started.")
            host._emit_ranking_step(
                "abstract_enrichment",
                "processing",
                "Abstract enrichment",
                current=0,
                total=max(1, len(ranked)),
                detail="Fetching missing abstracts when available.",
            )
            ranked = host._enrich_with_abstracts(ranked)
            host._emit_log("External abstract enrichment completed.")
            host._emit_ranking_step(
                "abstract_enrichment",
                "complete",
                "Abstract enrichment",
                current=len(ranked),
                total=max(1, len(ranked)),
                detail="Abstract enrichment completed.",
            )

        host._emit_stage(
            "ranking",
            "complete",
            ranked_count=len(ranked),
            ranking_steps=list(host.ranking_steps.values()),
            **ranking_context,
        )

        host._emit_stage("results", "complete", ranked_count=len(ranked), total=total)

        return {
            "question": question,
            "search_intent": host.search_intent,
            "search_plan": host.search_plan.model_dump() if host.search_plan else {},
            "query_view_selection": list(host.query_view_selection),
            "query_portfolio": list(host.query_portfolio),
            "query_iteration_memory": host._query_iteration_memory_payload(),
            "final_query": query,
            "db": host.config.wos_db if host.data_source == "wos" else host.data_source.upper(),
            "source": host.data_source,
            "field": host._field_summary(),
            "total": total,
            "iterations": iteration,
            "history": history,
            "search_state": host._search_state_payload(),
            "citation_map": host.citation_map,
            "ranking_steps": list(host.ranking_steps.values()),
            "ranked": ranked,
        }
