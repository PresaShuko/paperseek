from __future__ import annotations

from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer


TOOL_NAMES = (
    "start_search",
    "get_search_status",
    "get_search_events",
    "get_search_results",
    "get_citation_graph",
    "cancel_search",
    "export_results",
    "list_sources",
    "get_source_capabilities",
)


class PaperSeekApplication(Protocol):
    def start_search(self, **values) -> dict: ...
    def get_search_status(self, **values) -> dict: ...
    def get_search_events(self, **values) -> dict: ...
    def get_search_results(self, **values) -> dict: ...
    def get_citation_graph(self, **values) -> dict: ...
    def cancel_search(self, **values) -> dict: ...
    def export_results(self, **values) -> dict: ...
    def list_sources(self) -> dict: ...
    def get_source_capabilities(self, **values) -> dict: ...


def register_tools(server: MCPServer, application: PaperSeekApplication) -> None:
    @server.tool(name="start_search", structured_output=True)
    def start_search(
        question: str,
        source: str = "openalex",
        search_budget: str = "fast",
        field_ids: list[str] | None = None,
        field_hint: str = "",
        citation_enabled: bool | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Start a durable PaperSeek run and return its run_id immediately."""
        return application.start_search(
            question=question,
            source=source,
            search_budget=search_budget,
            field_ids=field_ids or [],
            field_hint=field_hint,
            citation_enabled=citation_enabled,
            idempotency_key=idempotency_key,
        )

    @server.tool(name="get_search_status", structured_output=True)
    def get_search_status(run_id: str) -> dict[str, Any]:
        """Return the persisted run snapshot for a durable search."""
        return application.get_search_status(run_id=run_id)

    @server.tool(name="get_search_events", structured_output=True)
    def get_search_events(run_id: str, after_sequence: int = 0, limit: int = 100) -> dict[str, Any]:
        """Return persisted events after a sequence cursor."""
        return application.get_search_events(
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @server.tool(name="get_search_results", structured_output=True)
    def get_search_results(
        run_id: str,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Return a cursor-paginated page of persisted search results."""
        return application.get_search_results(
            run_id=run_id,
            cursor=cursor,
            page_size=page_size,
        )

    @server.tool(name="get_citation_graph", structured_output=True)
    def get_citation_graph(run_id: str) -> dict[str, Any]:
        """Return the persisted citation graph for a completed run."""
        return application.get_citation_graph(run_id=run_id)

    @server.tool(name="cancel_search", structured_output=True)
    def cancel_search(run_id: str) -> dict[str, Any]:
        """Request logical cancellation of a queued or running search."""
        return application.cancel_search(run_id=run_id)

    @server.tool(name="export_results", structured_output=True)
    def export_results(run_id: str, format: str = "json") -> dict[str, Any]:
        """Return a complete persisted JSON or CSV export."""
        return application.export_results(run_id=run_id, format=format)

    @server.tool(name="list_sources", structured_output=True)
    def list_sources() -> dict[str, Any]:
        """List all supported literature sources and their descriptors."""
        return application.list_sources()

    @server.tool(name="get_source_capabilities", structured_output=True)
    def get_source_capabilities(source: str) -> dict[str, Any]:
        """Return the descriptor and capabilities for one source."""
        return application.get_source_capabilities(source=source)


__all__ = ["PaperSeekApplication", "TOOL_NAMES", "register_tools"]
