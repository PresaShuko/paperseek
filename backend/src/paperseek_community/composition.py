from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from paperseek_app.execution import WorkflowExecution
from paperseek_app.models import RunDetail
from paperseek_app.services import RunService
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.fixed_source import FixedLLMAdapter, FixedSourceAdapter
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.llm import CommunityLLMAdapter
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.worker import EmbeddedRunExecutor
from paperseek_core.budgets import workflow_budget
from paperseek_core.execution import RequestContext
from paperseek_core.models import QueryLoopBudget, ResearchWorkflowRequest
from paperseek_core.ports import AbstractPort, CancellationToken
from paperseek_core.sources import AsyncHttpTransport
from paperseek_core.sources.arxiv import ArxivSource
from paperseek_core.sources.crossref import CrossrefSource
from paperseek_core.sources.google_scholar import GoogleScholarSource
from paperseek_core.sources.openalex import OpenAlexSource
from paperseek_core.sources.paperhub import PaperHubSource
from paperseek_core.sources.pubmed import PubMedSource
from paperseek_core.sources.semantic_scholar import SemanticScholarSource
from paperseek_core.sources.wos import WosSource


def community_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


class CommunityExecutionResolver:
    def __init__(
        self,
        settings: CommunityDeploymentSettings,
        credentials: EncryptedRunCredentialStore,
    ) -> None:
        self.settings = settings
        self.credentials = credentials

    def __call__(self, run: RunDetail, cancellation: CancellationToken) -> WorkflowExecution:
        stored = self.credentials.resolve(run.id)
        llm_credentials = stored.get("llm", {})
        source_credentials = stored.get("source", {})
        route = self.settings.llm_route(dict(run.config_snapshot.get("llm") or {}))
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        transport = AsyncHttpTransport(
            client=client,
            context=RequestContext(step_key="source.request", cancellation=cancellation),
        )
        source = self._source(
            run.source,
            transport,
            source_credentials.get("api_key", ""),
        )
        budget_name = str(run.config_snapshot.get("search_budget") or "medium")
        field = str(run.config_snapshot.get("field") or "").strip()
        query_budget, preset = workflow_budget(
            budget_name,
            field_ids=(field,) if field else (),
        )
        llm = CommunityLLMAdapter(
            client=client,
            cancellation=cancellation,
            api_type=route["api_type"],
            base_url=route["base_url"],
            model=route["model"],
            api_key=llm_credentials.get("api_key") or self.settings.llm_api_key,
        )
        abstracts = source if isinstance(source, AbstractPort) else None
        return WorkflowExecution(
            llm=llm,
            source=source,
            abstracts=abstracts,
            request=ResearchWorkflowRequest(
                question=run.question,
                query_budget=query_budget,
                citation_enabled=bool(run.config_snapshot.get("citation_enabled", True)),
                citation_seed_count=preset.citation_seed_count,
                citation_per_seed=preset.citation_per_seed,
                citation_max_records=preset.citation_max_records,
                citation_depth=preset.citation_depth,
            ),
            close=client.aclose,
        )

    def _source(
        self,
        name: str,
        transport: AsyncHttpTransport,
        submitted_key: str,
    ):
        key = submitted_key or {
            "openalex": self.settings.openalex_api_key,
            "semanticscholar": self.settings.semantic_scholar_api_key,
            "pubmed": self.settings.pubmed_api_key,
            "wos": self.settings.wos_api_key,
            "googlescholar": self.settings.google_scholar_api_key,
        }.get(name, "")
        factories = {
            "openalex": lambda: OpenAlexSource(
                transport=transport,
                api_key=key,
                email=self.settings.contact_email,
            ),
            "arxiv": lambda: ArxivSource(transport=transport),
            "crossref": lambda: CrossrefSource(
                transport=transport,
                email=self.settings.contact_email,
            ),
            "semanticscholar": lambda: SemanticScholarSource(transport=transport, api_key=key),
            "pubmed": lambda: PubMedSource(
                transport=transport,
                api_key=key,
                email=self.settings.contact_email,
            ),
            "wos": lambda: WosSource(transport=transport, api_key=key),
            "googlescholar": lambda: GoogleScholarSource(transport=transport, api_key=key),
            "paperhub": lambda: PaperHubSource(transport=transport),
        }
        try:
            return factories[name]()
        except KeyError as exc:
            raise ValueError("The queued run selected an unsupported source.") from exc


def execute_fixture_search(
    database_path: Path | str,
    fixture_path: Path | str,
    question: str,
    *,
    owner_id: str,
    clock: Callable[[], datetime] | None = None,
) -> RunDetail:
    migrate_database(database_path)
    source = FixedSourceAdapter.from_file(fixture_path)
    uow = SQLiteRunUnitOfWork(database_path, clock=clock)
    try:
        service = RunService(
            uow,
            FileArtifactStore(Path(database_path).expanduser().resolve().parent),
        )
        run = service.create_run(
            question,
            source.name,
            {"fixture_id": source.fixture.fixture_id},
        )
        def resolve(detail: RunDetail, _cancellation: CancellationToken) -> WorkflowExecution:
            current = FixedSourceAdapter.from_file(fixture_path)
            if detail.config_snapshot.get("fixture_id") != current.fixture.fixture_id:
                raise ValueError("The queued run does not match the fixed workflow fixture.")
            return WorkflowExecution(
                llm=FixedLLMAdapter(current.fixture.llm_responses),
                source=current,
                abstracts=current,
                request=ResearchWorkflowRequest(
                    question=detail.question,
                    query_budget=QueryLoopBudget(
                        target_min=1,
                        target_max=50,
                        retrieval_pool_min=1,
                        query_portfolio_enabled=False,
                    ),
                ),
            )

        executor = EmbeddedRunExecutor(service, resolve, owner_id=owner_id)

        async def execute_until_created() -> RunDetail:
            while True:
                detail = await executor.run_once()
                if detail is None:
                    raise RuntimeError("The queued fixture run was not claimed.")
                if detail.id == run.id:
                    return detail

        return asyncio.run(
            execute_until_created()
        )
    finally:
        uow.close()
