from __future__ import annotations

import base64
import binascii
from datetime import datetime
import json

from paperseek_app.errors import ArtifactNotFound, InvalidCursor, InvalidResultQuery
from paperseek_app.models import (
    ArtifactContent,
    ArtifactDescriptor,
    ArtifactRole,
    ArtifactVisibility,
    HistoryItem,
    HistoryPage,
    PersistedEvent,
    PersistedResult,
    ResultPage,
    RunAudit,
    RunDetail,
    StoredArtifact,
)
from paperseek_app.ports import ArtifactStore, RunUnitOfWork


class RunQueryService:
    _MAX_PAGE_SIZE = 200

    def __init__(self, uow: RunUnitOfWork, artifact_store: ArtifactStore) -> None:
        self.uow = uow
        self.artifact_store = artifact_store

    def get_run(self, run_id: str) -> RunDetail:
        return self.uow.get_run(run_id)

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[PersistedEvent]:
        run = self.uow.get_run(run_id)
        return self.uow.list_events(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def get_run_log(self, run_id: str) -> str:
        lines = []
        for event in self.list_events(run_id):
            payload = json.dumps(event.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            lines.append(f"{event.sequence:06d} {event.occurred_at.isoformat()} {event.event_type} {payload}")
        return "\n".join(lines) + ("\n" if lines else "")

    def get_results(self, run_id: str) -> list[PersistedResult]:
        self.uow.get_run(run_id)
        return self.uow.get_results(run_id)

    def list_artifacts(self, run_id: str) -> list[StoredArtifact]:
        self.uow.get_run(run_id)
        return self.uow.list_artifacts(run_id)

    _RESULT_SORTS = frozenset({"rank", "score", "citations", "year"})
    _RESULT_METADATA_FILTERS = frozenset({"abstract", "doi", "pdf"})

    def get_result_page(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
        query: str | None = None,
        min_score: float | None = None,
        metadata: str | None = None,
        sort: str = "rank",
    ) -> ResultPage:
        self._validate_page_size(page_size)
        if sort not in self._RESULT_SORTS:
            raise InvalidResultQuery("The result sort is unsupported.")
        if metadata is not None and metadata not in self._RESULT_METADATA_FILTERS:
            raise InvalidResultQuery("The metadata filter is unsupported.")
        if min_score is not None and not 0 <= min_score <= 10:
            raise InvalidResultQuery("The minimum score is out of range.")
        run = self.uow.get_run(run_id)
        items = [
            item.model_copy(
                update={"metadata_status": self._metadata_status(item.record, run.warnings)}
            )
            for item in self.uow.get_results(run_id)
        ]
        fingerprint = self._result_fingerprint(query, min_score, metadata, sort)
        offset = 0
        if cursor:
            payload = self._decode_cursor(cursor, "results")
            if payload.get("run_id") != run_id or payload.get("filter") != fingerprint:
                raise InvalidCursor("The result cursor belongs to another run or filter.")
            try:
                offset = int(payload["offset"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidCursor("The result cursor is invalid.") from exc
            if offset < 1:
                raise InvalidCursor("The result cursor is invalid.")
        matched = [
            item
            for item in items
            if self._result_matches(item.record, query, min_score, metadata)
        ]
        ordered = self._sort_results(matched, sort)
        visible = ordered[offset:offset + page_size]
        next_cursor = None
        if len(ordered) > offset + page_size:
            next_cursor = self._encode_cursor(
                {
                    "scope": "results",
                    "run_id": run_id,
                    "filter": fingerprint,
                    "offset": offset + page_size,
                }
            )
        scored = [item.record.score for item in items if item.record.score is not None]
        return ResultPage(
            results=visible,
            next_cursor=next_cursor,
            total_count=len(items),
            matched_count=len(matched),
            scored_count=len(scored),
            max_score=max(scored) if scored else None,
        )

    @staticmethod
    def _result_fingerprint(
        query: str | None,
        min_score: float | None,
        metadata: str | None,
        sort: str,
    ) -> str:
        return json.dumps(
            {
                "query": (query or "").strip(),
                "min_score": min_score,
                "metadata": metadata or "",
                "sort": sort,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _result_matches(
        record,
        query: str | None,
        min_score: float | None,
        metadata: str | None,
    ) -> bool:
        if min_score is not None and (record.score is None or record.score < min_score):
            return False
        if metadata == "abstract" and not record.abstract.strip():
            return False
        if metadata == "doi" and not record.doi.strip():
            return False
        if metadata == "pdf" and not record.pdf_url.strip():
            return False
        if query and query.strip():
            haystack = " ".join(
                [
                    record.title,
                    record.authors_text,
                    record.abstract,
                    record.doi,
                    record.venue,
                    record.source,
                    record.keywords_text,
                ]
            ).casefold()
            if query.strip().casefold() not in haystack:
                return False
        return True

    @staticmethod
    def _sort_results(items: list[PersistedResult], sort: str) -> list[PersistedResult]:
        if sort == "score":
            return sorted(
                items,
                key=lambda item: (
                    item.record.score is None,
                    -(item.record.score or 0),
                    item.rank,
                ),
            )
        if sort == "citations":
            return sorted(items, key=lambda item: (-item.record.citation_count, item.rank))
        if sort == "year":
            return sorted(
                items,
                key=lambda item: (
                    -(item.record.publish_year or item.record.year or 0),
                    item.rank,
                ),
            )
        return sorted(items, key=lambda item: item.rank)

    @staticmethod
    def _metadata_status(record, warnings: list[str]) -> str:
        doi = record.doi.strip()
        if doi and f"abstract_enrichment_failed:{doi}" in warnings:
            return "degraded"
        if doi and f"abstract_enrichment_unavailable:{doi}" in warnings:
            return "unavailable"
        if record.abstract:
            return "complete"
        return "unavailable" if doi else "not_requested"

    def get_history_page(
        self,
        *,
        cursor: str | None = None,
        page_size: int = 50,
        query: str | None = None,
    ) -> HistoryPage:
        self._validate_page_size(page_size)
        if query is not None and query.strip():
            return self._search_history_page(cursor=cursor, page_size=page_size, query=query)
        before_created_at = None
        before_id = None
        if cursor:
            payload = self._decode_cursor(cursor, "history")
            try:
                before_created_at = datetime.fromisoformat(str(payload["created_at"]))
                before_id = str(payload["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidCursor("The history cursor is invalid.") from exc
            if not before_id or before_created_at.tzinfo is None:
                raise InvalidCursor("The history cursor is invalid.")
        rows = self.uow.list_history(
            before_created_at=before_created_at,
            before_id=before_id,
            limit=page_size + 1,
        )
        visible = rows[:page_size]
        items = [self._history_item(item) for item in visible]
        next_cursor = None
        if len(rows) > page_size:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                {
                    "scope": "history",
                    "created_at": last.created_at.isoformat(),
                    "id": last.id,
                }
            )
        return HistoryPage(items=items, next_cursor=next_cursor)

    def _search_history_page(
        self,
        *,
        cursor: str | None,
        page_size: int,
        query: str,
    ) -> HistoryPage:
        needle = query.strip().casefold()
        offset = 0
        if cursor:
            payload = self._decode_cursor(cursor, "history-search")
            if payload.get("query") != needle:
                raise InvalidCursor("The history cursor belongs to another search.")
            try:
                offset = int(payload["offset"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidCursor("The history cursor is invalid.") from exc
            if offset < 1:
                raise InvalidCursor("The history cursor is invalid.")
        matched = [
            item
            for item in self._list_all_history_items()
            if needle
            in " ".join([item.question, item.source, item.status, item.error_code]).casefold()
        ]
        visible = matched[offset:offset + page_size]
        next_cursor = None
        if len(matched) > offset + page_size:
            next_cursor = self._encode_cursor(
                {"scope": "history-search", "query": needle, "offset": offset + page_size}
            )
        return HistoryPage(items=visible, next_cursor=next_cursor, matched_count=len(matched))

    def _list_all_history_items(self) -> list[HistoryItem]:
        items: list[HistoryItem] = []
        before_created_at = None
        before_id = None
        while True:
            rows = self.uow.list_history(
                before_created_at=before_created_at,
                before_id=before_id,
                limit=self._MAX_PAGE_SIZE + 1,
            )
            visible = rows[: self._MAX_PAGE_SIZE]
            items.extend(self._history_item(item) for item in visible)
            if len(rows) <= self._MAX_PAGE_SIZE:
                return items
            last = visible[-1]
            before_created_at = last.created_at
            before_id = last.id

    @staticmethod
    def _history_item(item) -> HistoryItem:
        return HistoryItem(
            id=item.id,
            question=item.question,
            source=item.source,
            status=item.status,
            result_count=item.result_count,
            error_code=item.error_code,
            warnings=item.warnings,
            created_at=item.created_at,
            finished_at=item.finished_at,
        )

    def list_user_artifacts(self, run_id: str) -> list[ArtifactDescriptor]:
        self.uow.get_run(run_id)
        return [
            self._artifact_descriptor(item)
            for item in self.uow.list_artifacts(run_id)
            if item.visibility is ArtifactVisibility.USER
            and item.role in {ArtifactRole.COMPLETION_REQUIRED, ArtifactRole.AUDIT}
        ]

    def read_user_artifact(self, run_id: str, artifact_id: str) -> ArtifactContent:
        self.uow.get_run(run_id)
        artifact = next(
            (
                item
                for item in self.uow.list_artifacts(run_id)
                if item.id == artifact_id
                and item.visibility is ArtifactVisibility.USER
                and item.role in {ArtifactRole.COMPLETION_REQUIRED, ArtifactRole.AUDIT}
            ),
            None,
        )
        if artifact is None:
            raise ArtifactNotFound("The user artifact was not found.")
        return self._artifact_content(artifact)

    def get_export(self, run_id: str, export_format: str) -> ArtifactContent:
        kind = {"json": "export_json", "csv": "export_csv"}.get(export_format.casefold())
        if kind is None:
            raise ValueError("The export format must be json or csv.")
        return self._read_user_artifact_by_kind(run_id, kind)

    def get_citation_map(self, run_id: str) -> ArtifactContent:
        return self._read_user_artifact_by_kind(run_id, "citation_map")

    def get_run_audit(self, run_id: str) -> RunAudit:
        content = self._read_user_artifact_by_kind(run_id, "final_result")
        payload = json.loads(content.content)
        search_state = dict(payload.get("search_state") or {})
        queue = dict(search_state.get("candidate_queue") or {})
        ledger = dict(queue.get("ledger") or {})
        summary = dict(queue.get("ledger_summary") or {})
        lifecycle = dict(summary.get("lifecycle_candidate_counts") or {})
        ranking_steps = list(payload.get("ranking_steps") or [])
        selected_for_llm = int(lifecycle.get("selected_for_llm") or 0)
        if not selected_for_llm:
            reranking = next(
                (item for item in reversed(ranking_steps) if item.get("id") == "llm_reranking"),
                {},
            )
            selected_for_llm = int(reranking.get("candidate_count") or 0)
        ranked = list(payload.get("ranked") or [])
        ledger_candidates = int(summary.get("total_candidates") or len(ledger) or len(queue.get("keys") or []))
        ledger_retained = int(summary.get("serialized_candidates") or len(ledger))

        recovery = {key: 0 for key in ("query", "retrieval", "citation", "ranking", "enrichment")}
        recovery_event = next(
            (event for event in reversed(self.list_events(run_id)) if event.event_type == "workflow.recovery"),
            None,
        )
        if recovery_event is not None:
            for key in recovery:
                recovery[key] = int(recovery_event.payload.get(key) or 0)
        else:
            recovery["query"] = sum(
                event.event_type == "query.resumed" for event in self.list_events(run_id)
            )
        recovery["total"] = sum(recovery.values())

        history = list(payload.get("history") or [])
        return RunAudit(
            query_portfolio=list(payload.get("query_portfolio") or []),
            loop_decisions=[item for item in history if item.get("action") != "portfolio"],
            candidate_queue=queue,
            candidate_lifecycle={
                "ledger_candidates": ledger_candidates,
                "selected_for_llm": selected_for_llm,
                "final_output": int(lifecycle.get("final_output") or len(ranked)),
                "ledger_retained": ledger_retained,
            },
            recovery=recovery,
        )

    def _read_user_artifact_by_kind(self, run_id: str, kind: str) -> ArtifactContent:
        self.uow.get_run(run_id)
        artifact = next(
            (
                item
                for item in self.uow.list_artifacts(run_id)
                if item.kind == kind
                and item.visibility is ArtifactVisibility.USER
                and item.role in {ArtifactRole.COMPLETION_REQUIRED, ArtifactRole.AUDIT}
            ),
            None,
        )
        if artifact is None:
            raise ArtifactNotFound("The requested artifact was not found.")
        return self._artifact_content(artifact)

    def _artifact_content(self, artifact: StoredArtifact) -> ArtifactContent:
        return ArtifactContent(
            id=artifact.id,
            filename=artifact.filename,
            media_type=artifact.media_type,
            sha256=artifact.sha256,
            size=artifact.size,
            content=self.artifact_store.read(artifact),
        )

    @staticmethod
    def _artifact_descriptor(artifact: StoredArtifact) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            id=artifact.id,
            kind=artifact.kind,
            filename=artifact.filename,
            media_type=artifact.media_type,
            sha256=artifact.sha256,
            size=artifact.size,
            schema_version=artifact.schema_version,
            created_at=artifact.created_at,
            download_url=f"/api/v1/runs/{artifact.run_id}/artifacts/{artifact.id}",
        )

    @classmethod
    def _validate_page_size(cls, page_size: int) -> None:
        if page_size < 1 or page_size > cls._MAX_PAGE_SIZE:
            raise ValueError("Page size must be between 1 and 200.")

    @staticmethod
    def _encode_cursor(payload: dict) -> str:
        content = json.dumps(
            {"version": 1, **payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(content).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str, scope: str) -> dict:
        try:
            padding = "=" * (-len(cursor) % 4)
            payload = json.loads(base64.b64decode(cursor + padding, altchars=b"-_", validate=True))
        except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise InvalidCursor("The cursor is invalid.") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1 or payload.get("scope") != scope:
            raise InvalidCursor("The cursor is invalid for this resource.")
        return payload
