from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from paperseek.application.run_lease import RunOwnershipLost
from paperseek.application.search_service import SearchRunSession
from paperseek.run_executor import InProcessRunExecutor
from paperseek_core.execution import SearchCancelled


AgentFactory = Callable[[Callable[[dict[str, Any]], None]], Any]
ResponseEnricher = Callable[[dict[str, Any]], None]
ErrorFormatter = Callable[[Exception], str]
SessionFactory = Callable[[str], SearchRunSession]


def submit_background_search(
    executor: InProcessRunExecutor,
    session_factory: SessionFactory,
    agent_factory: AgentFactory,
    *,
    response_enricher: Optional[ResponseEnricher] = None,
    error_formatter: ErrorFormatter = str,
    run_event: Optional[dict[str, Any]] = None,
) -> str:
    """Start one persisted search without retaining an in-memory event stream."""

    run = executor.create(buffer_events=False)
    session = session_factory(run.owner_id)
    run_id = session.start()
    if not run_id:
        raise RuntimeError("Search history storage did not create a run record.")
    run.bind(run_id)

    def persist(event: dict[str, Any]) -> None:
        session.record_event(event)

    def worker() -> None:
        try:
            persist({**(run_event or {}), "type": "run", "run_id": run_id})
            session.config.validate()
            agent = agent_factory(persist)
            result = session.invoke(
                agent,
                event_handler=persist,
                cancel_check=run.is_cancelled,
            )
            response = session.response(result)
            if response_enricher is not None:
                response_enricher(response)
            session.complete(response)
        except SearchCancelled as exc:
            session.cancel(str(exc) or "Search cancelled by user.")
        except RunOwnershipLost:
            pass
        except Exception as exc:
            session.fail(error_formatter(exc))
        finally:
            run.close()

    run.start(worker)
    return run_id
