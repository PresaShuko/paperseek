from __future__ import annotations

from contextlib import closing
from importlib.resources import files
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import URL


def database_url(database_path: Path | str) -> URL:
    path = Path(database_path).expanduser().resolve()
    return URL.create("sqlite+pysqlite", database=str(path))


def migrate_database(database_path: Path | str) -> int:
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option(
        "script_location",
        str(files("paperseek_community.migrations")),
    )
    config.set_main_option(
        "sqlalchemy.url",
        database_url(path).render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
