from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptedRunCredentialStore:
    """Short-lived Community BYOK storage; plaintext never enters run state."""

    KEY_VERSION = 1

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.key_path = self.database_path.parent / "credentials.master.key"

    def save(self, run_id: str, credentials: dict[str, dict[str, str]]) -> None:
        normalized = {
            kind: {key: str(value) for key, value in values.items() if str(value)}
            for kind, values in credentials.items()
            if any(str(value) for value in values.values())
        }
        if not normalized:
            return
        key = self._load_or_create_key()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=25)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            for kind, values in normalized.items():
                nonce = os.urandom(12)
                ciphertext = AESGCM(key).encrypt(
                    nonce,
                    json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                    self._aad(run_id, kind),
                )
                connection.execute(
                    """
                    INSERT INTO run_credentials (
                        run_id, credential_kind, ciphertext, nonce,
                        key_version, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, credential_kind) DO UPDATE SET
                        ciphertext = excluded.ciphertext,
                        nonce = excluded.nonce,
                        key_version = excluded.key_version,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        run_id,
                        kind,
                        ciphertext,
                        nonce,
                        self.KEY_VERSION,
                        now.isoformat(timespec="microseconds"),
                        expires_at.isoformat(timespec="microseconds"),
                    ),
                )
            connection.commit()

    def resolve(self, run_id: str) -> dict[str, dict[str, str]]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT credential_kind, ciphertext, nonce, key_version, expires_at
                FROM run_credentials WHERE run_id = ?
                """,
                (run_id,),
            ).fetchall()
        if not rows:
            return {}
        key = self._load_or_create_key()
        now = datetime.now(timezone.utc)
        resolved: dict[str, dict[str, str]] = {}
        for kind, ciphertext, nonce, key_version, expires_at in rows:
            if key_version != self.KEY_VERSION or datetime.fromisoformat(expires_at) <= now:
                continue
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, self._aad(run_id, kind))
            values = json.loads(plaintext)
            if isinstance(values, dict):
                resolved[kind] = {str(name): str(value) for name, value in values.items()}
        return resolved

    def delete(self, run_id: str) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DELETE FROM run_credentials WHERE run_id = ?", (run_id,))
            connection.commit()

    def _load_or_create_key(self) -> bytes:
        try:
            key = self.key_path.read_bytes()
        except FileNotFoundError:
            key = os.urandom(32)
            try:
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = self.key_path.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
        if len(key) != 32:
            raise RuntimeError("The Community credential master key is invalid.")
        return key

    @classmethod
    def _aad(cls, run_id: str, kind: str) -> bytes:
        return f"paperseek.run_credentials|{run_id}|{kind}|{cls.KEY_VERSION}".encode("utf-8")
