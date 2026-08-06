from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional

from paperseek.application.run_lease import RunOwnershipLost
from paperseek.application.search_service import SearchRunSession
from paperseek.config import AgentConfig
from paperseek.run_executor import InProcessRunExecutor
from paperseek_core.execution import SearchCancelled


EventSink = Callable[[dict[str, Any]], None]
ConfigFactory = Callable[[], AgentConfig]
SessionFactory = Callable[[AgentConfig, str], SearchRunSession]
AgentFactory = Callable[[AgentConfig, EventSink], Any]
StartupEvents = Callable[[AgentConfig], Iterable[dict[str, Any]]]
ResponseEnricher = Callable[[dict[str, Any], EventSink], None]
CompletionEvents = Callable[[dict[str, Any]], Iterable[dict[str, Any]]]
ErrorEventFactory = Callable[[Exception, Optional[AgentConfig]], dict[str, Any]]
UnexpectedErrorHandler = Callable[[Exception], None]


def stream_persisted_search(
    executor: InProcessRunExecutor,
    config_factory: ConfigFactory,
    session_factory: SessionFactory,
    agent_factory: AgentFactory,
    *,
    startup_events: Optional[StartupEvents] = None,
    response_enricher: Optional[ResponseEnricher] = None,
    completion_events: Optional[CompletionEvents] = None,
    error_event_factory: Optional[ErrorEventFactory] = None,
    unexpected_error_handler: Optional[UnexpectedErrorHandler] = None,
    heartbeat_seconds: float = 10.0,
    heartbeat_factory: Optional[Callable[[], dict[str, Any]]] = None,
) -> Iterator[dict[str, Any]]:
    """Execute one compatibility stream with persisted ownership semantics."""

    session: Optional[SearchRunSession] = None
    config: Optional[AgentConfig] = None
    run = executor.create()

    def send(event: dict[str, Any]) -> None:
        if event.get("type") != "result" and session is not None:
            session.record_event(event)
        run.emit(event)

    def send_terminal(event: dict[str, Any]) -> None:
        try:
            send(event)
        except RunOwnershipLost:
            run.emit(event)

    def worker() -> None:
        nonlocal config, session
        try:
            config = config_factory()
            session = session_factory(config, run.owner_id)
            session.start()
            run.bind(session.run_id)
            if session.run_id:
                send({"type": "run", "run_id": session.run_id})
            if startup_events is not None:
                for event in startup_events(config):
                    send(event)
            config.validate()
            send({"type": "log", "message": "Initializing LLM client."})
            agent = agent_factory(config, send)
            send({"type": "log", "message": "Initializing source adapter."})
            result = session.invoke(
                agent,
                event_handler=send,
                cancel_check=run.is_cancelled,
            )
            response = session.response(result)
            if response_enricher is not None:
                response_enricher(response, send)
            session.complete(response)
            if completion_events is not None:
                for event in completion_events(response):
                    send(event)
            send({"type": "result", "data": response})
            send({"type": "log", "message": "Run completed successfully."})
        except SearchCancelled as exc:
            message = str(exc) or "Search cancelled by user."
            if session is not None:
                session.cancel(message)
            send_terminal({"type": "cancelled", "message": message})
        except RunOwnershipLost as exc:
            run.emit({"type": "error", "message": str(exc)})
        except Exception as exc:
            if unexpected_error_handler is not None:
                unexpected_error_handler(exc)
            event = (
                error_event_factory(exc, config)
                if error_event_factory is not None
                else {"type": "error", "message": str(exc)}
            )
            if session is not None:
                session.fail(str(event.get("message") or exc))
            send_terminal(event)
        finally:
            run.close()

    run.start(worker)
    yield from run.iter_events(
        heartbeat_seconds=heartbeat_seconds,
        heartbeat_factory=heartbeat_factory,
    )
