from __future__ import annotations

from typing import Any, Dict, List, Tuple

from paperseek_core.harness import CandidateCitationPath
from paperseek_core.retrieval import document_alias_keys, document_key
from paperseek_core.sources.contracts import CitationSeedPlan


def citation_count(document: Any) -> int:
    return sum(
        int(getattr(citation, "count", 0) or 0)
        for citation in (getattr(document, "citations", None) or [])
    )


class CitationSupport:
    """Citation planning and graph bookkeeping outside the agent."""

    def __init__(self, host: Any) -> None:
        self.host = host

    @staticmethod
    def seed_key(document: Any) -> str:
        if not document:
            return ""
        identifiers = getattr(document, "identifiers", None)
        for value in (
            getattr(identifiers, "openalex", "") if identifiers else "",
            getattr(identifiers, "doi", "") if identifiers else "",
            getattr(document, "uid", ""),
            getattr(document, "title", ""),
        ):
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized
        return ""

    def build_seed_plans(self, seed_ranked: list, candidates: list, plan: Any) -> list:
        seed_limit = max(1, int(getattr(plan, "seed_limit", 1) or 1))
        depth = max(1, min(int(getattr(plan, "depth", 1) or 1), 3))
        relevance_quota = max(1, int(getattr(plan, "relevance_quota", seed_limit // 2) or 1))
        impact_quota = max(0, int(getattr(plan, "impact_quota", 0) or 0))
        recent_quota = max(
            0,
            int(
                getattr(
                    plan,
                    "recent_quota",
                    max(0, seed_limit - relevance_quota - impact_quota),
                )
                or 0
            ),
        )
        plans: List[CitationSeedPlan] = []
        index_by_key: Dict[str, CitationSeedPlan] = {}

        def add_plan(document: Any, role: str, directions: Tuple[str, ...]) -> None:
            key = self.seed_key(document)
            if not document or not key:
                return
            if len(plans) >= seed_limit and key not in index_by_key:
                return
            existing = index_by_key.get(key)
            if existing:
                merged = list(dict.fromkeys(tuple(existing.directions) + tuple(directions)))
                existing.directions = tuple(merged)
                if role not in existing.role.split("+"):
                    existing.role = f"{existing.role}+{role}"
                existing.depth = max(existing.depth, depth)
                return
            seed_plan = CitationSeedPlan(
                record=document,
                role=role,
                directions=directions,
                depth=depth,
            )
            index_by_key[key] = seed_plan
            plans.append(seed_plan)

        relevance_documents = [
            entry.get("document")
            for entry in seed_ranked
            if entry.get("document") is not None and float(entry.get("score") or 0) >= 7
        ]
        if len(relevance_documents) < relevance_quota:
            for entry in seed_ranked:
                document = entry.get("document")
                if document is not None and document not in relevance_documents:
                    relevance_documents.append(document)
                if len(relevance_documents) >= relevance_quota:
                    break
        for document in relevance_documents[:relevance_quota]:
            add_plan(document, "relevance", ("backward", "forward"))

        impact_documents = sorted(
            candidates or [],
            key=lambda document: (
                citation_count(document),
                getattr(getattr(document, "source", None), "publish_year", 0) or 0,
            ),
            reverse=True,
        )
        for document in impact_documents[:impact_quota]:
            add_plan(document, "impact", ("backward",))

        recent_documents = sorted(
            candidates or [],
            key=lambda document: (
                getattr(getattr(document, "source", None), "publish_year", 0) or 0,
                citation_count(document),
            ),
            reverse=True,
        )
        for document in recent_documents[:recent_quota]:
            add_plan(document, "recent", ("forward",))

        if len(plans) < seed_limit:
            for entry in seed_ranked:
                add_plan(entry.get("document"), "relevance", ("backward", "forward"))
                if len(plans) >= seed_limit:
                    break

        buckets: Dict[str, List[CitationSeedPlan]] = {
            "relevance": [],
            "impact": [],
            "recent": [],
        }
        for seed_plan in plans:
            roles = set(str(seed_plan.role or "relevance").split("+"))
            bucket = "recent" if "recent" in roles else "impact" if "impact" in roles else "relevance"
            buckets[bucket].append(seed_plan)
        interleaved: List[CitationSeedPlan] = []
        while any(buckets.values()):
            for role in ("relevance", "impact", "recent"):
                if buckets[role]:
                    interleaved.append(buckets[role].pop(0))
        return interleaved

    @staticmethod
    def seed_plan_counts(seed_plans: list) -> dict:
        counts: Dict[str, int] = {"relevance": 0, "impact": 0, "recent": 0}
        for plan in seed_plans or []:
            for role in str(getattr(plan, "role", "") or "").split("+"):
                if role in counts:
                    counts[role] += 1
        return counts

    @staticmethod
    def evidence_by_key(records: list, citation_data: dict) -> Dict[str, Dict[str, Any]]:
        edges = [edge for edge in (citation_data.get("edges") or []) if isinstance(edge, dict)]
        output: Dict[str, Dict[str, Any]] = {}
        for document in records or []:
            key = document_key(document)
            identifiers = getattr(document, "identifiers", None)
            node_id = str(
                getattr(document, "uid", "")
                or (getattr(identifiers, "openalex", "") if identifiers else "")
                or getattr(document, "title", "")
                or ""
            )
            if not key or not node_id:
                continue
            paths = []
            for edge in edges:
                edge_source = str(edge.get("source") or "")
                edge_target = str(edge.get("target") or "")
                edge_type = str(edge.get("type") or "")
                if edge_source == node_id and edge_type == "cites":
                    direction, parent_id = "forward", edge_target
                elif edge_target == node_id and edge_type == "references":
                    direction, parent_id = "backward", edge_source
                else:
                    continue
                try:
                    depth = max(0, int(edge.get("layer") or 0))
                except (TypeError, ValueError):
                    depth = 0
                paths.append(
                    CandidateCitationPath(
                        seed_id=str(edge.get("seed") or ""),
                        parent_id=parent_id,
                        direction=direction,
                        depth=depth,
                    )
                )
            output[key] = {
                "citation_paths": paths,
                "detail": f"citation_paths={len(paths)}",
            }
        return output

    def seed_candidate_pool(self, candidates: list, limit: int) -> list:
        limit = max(1, int(limit or 1))
        candidate_by_key = {
            document_key(document): document
            for document in candidates or []
            if document_key(document)
        }
        selected = []
        selected_keys = set()

        def add_documents(documents: list, quota: int) -> None:
            added = 0
            for document in documents or []:
                key = document_key(document)
                if not key or key not in candidate_by_key or key in selected_keys:
                    continue
                selected.append(candidate_by_key[key])
                selected_keys.add(key)
                added += 1
                if len(selected) >= limit or added >= quota:
                    break

        host = self.host
        view_types = {
            view.view_id: view.view_type
            for view in (host.search_plan.query_views if host.search_plan else [])
        }
        successor_ids = [
            view_id
            for view_id, view_type in view_types.items()
            if view_type == "successor_paradigm" and view_id in host.query_portfolio_lane_results
        ]
        successor_quota = max(1, limit // 2)
        for view_id in successor_ids:
            add_documents(host.query_portfolio_lane_results.get(view_id, []), successor_quota)
            if len(selected) >= limit:
                return selected

        other_ids = [
            view_id
            for view_id in host.query_portfolio_lane_results
            if view_id not in successor_ids
        ]
        remaining_for_views = max(0, (limit * 3 // 4) - len(selected))
        per_view_quota = max(1, remaining_for_views // max(1, len(other_ids)))
        for view_id in other_ids:
            add_documents(host.query_portfolio_lane_results.get(view_id, []), per_view_quota)
            if len(selected) >= limit:
                return selected

        add_documents(candidates, limit - len(selected))
        return selected

    def empty_map(
        self,
        enabled: bool = True,
        initial_candidates: int = 0,
        candidate_pool: int = 0,
    ) -> dict:
        return {
            "enabled": bool(enabled),
            "supported": self.host.data_source == "openalex",
            "status": "waiting",
            "initial_candidates": initial_candidates,
            "seed_count": 0,
            "added_candidates": 0,
            "candidate_pool": candidate_pool,
            "nodes": [],
            "edges": [],
        }

    def finalize_map(self, ranked: list) -> None:
        citation_map = self.host.citation_map
        if not citation_map:
            return
        nodes = {node.get("id"): node for node in citation_map.get("nodes", []) if node.get("id")}
        for index, entry in enumerate(ranked or [], 1):
            document = entry.get("document")
            if not document:
                continue
            node_id = (
                getattr(document, "uid", "")
                or getattr(getattr(document, "identifiers", None), "openalex", "")
                or getattr(document, "title", "")
            )
            if not node_id:
                continue
            source = getattr(document, "source", None)
            node = nodes.get(node_id)
            if not node:
                node = {
                    "id": node_id,
                    "title": getattr(document, "title", "") or "(no title)",
                    "year": getattr(source, "publish_year", None) if source else None,
                    "source": getattr(source, "source_title", "") if source else "",
                    "citations": citation_count(document),
                    "roles": [],
                    "seed_uids": [],
                }
                nodes[node_id] = node
            if "result" not in node["roles"]:
                node["roles"].append("result")
            node["rank"] = index
            node["score"] = entry.get("score", 0)
            node["reasoning"] = entry.get("reasoning", "")
        citation_map["nodes"] = list(nodes.values())

    @staticmethod
    def dedupe_documents(documents: list) -> list:
        deduped = []
        seen_aliases = set()
        for document in documents or []:
            aliases = document_alias_keys(document)
            if not aliases or any(alias in seen_aliases for alias in aliases):
                continue
            seen_aliases.update(aliases)
            deduped.append(document)
        return deduped
