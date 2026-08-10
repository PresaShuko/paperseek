from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from paperseek_app.services import RunService
from paperseek_community.api import create_app
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.composition import (
    CommunityExecutionResolver,
    community_static_dir,
    execute_fixture_search,
)
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperseek")
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="Run the deterministic research workflow fixture.")
    search.add_argument("question")
    search.add_argument("--database", type=Path, required=True)
    search.add_argument("--source-fixture", type=Path, required=True)

    serve = commands.add_parser("serve", help="Serve persisted research-run read models.")
    serve.add_argument("--database", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    migrate = commands.add_parser("migrate", help="Apply Community Alembic migrations.")
    migrate.add_argument("--database", type=Path, required=True)

    commands.add_parser("version", help="Print the PaperSeek version.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        print("0.3.0")
        return 0
    if args.command == "migrate":
        schema_version = migrate_database(args.database)
        print(json.dumps({"schema_version": schema_version, "status": "migrated"}, sort_keys=True))
        return 0
    if args.command == "serve":
        import uvicorn

        settings = CommunityDeploymentSettings.from_environment()
        credentials = EncryptedRunCredentialStore(args.database)
        uvicorn.run(
            create_app(
                args.database,
                execution_resolver=CommunityExecutionResolver(settings, credentials),
                static_dir=community_static_dir(),
                deployment_settings=settings,
                credential_store=credentials,
            ),
            host=args.host,
            port=args.port,
        )
        return 0

    detail = execute_fixture_search(
        args.database,
        args.source_fixture,
        args.question,
        owner_id=f"cli-{uuid4()}",
    )
    uow = SQLiteRunUnitOfWork(args.database)
    try:
        results = RunService(uow, FileArtifactStore(args.database.parent)).get_results(detail.id)
    finally:
        uow.close()
    print(
        json.dumps(
            {
                "run_id": detail.id,
                "status": detail.status.value,
                "source": detail.source,
                "result_count": detail.result_count,
                "results": [item.record.model_dump(mode="json") for item in results],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
