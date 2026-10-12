from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from paperseek_app.errors import (
    ArtifactConflict,
    ArtifactIntegrityError,
    ArtifactPersistenceError,
)
from paperseek_app.models import ArtifactWrite, StoredArtifact


_SAFE_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class FileArtifactStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        # Checkpoint names can exceed MAX_PATH below a valid Windows data folder.
        # Keep the extended prefix internal; stored keys remain portable and relative.
        if os.name == "nt":
            native_path = str(self.data_dir)
            if not native_path.startswith("\\\\?\\"):
                native_path = ("\\\\?\\UNC\\" + native_path[2:] if native_path.startswith("\\\\")
                               else "\\\\?\\" + native_path)
                self.data_dir = Path(native_path)
        self.artifact_root = self.data_dir / "artifacts"
        self.temp_root = self.artifact_root / ".tmp"

    def put(self, artifact: ArtifactWrite) -> StoredArtifact:
        target = self._target(artifact)
        digest = hashlib.sha256(artifact.content).hexdigest()
        if target.exists():
            return self._existing(artifact, target, digest)

        target.parent.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        temporary = self.temp_root / f"{uuid4()}.tmp"
        linked = False
        try:
            with temporary.open("xb") as stream:
                stream.write(artifact.content)
                stream.flush()
                os.fsync(stream.fileno())
            if temporary.stat().st_size != len(artifact.content):
                raise ArtifactIntegrityError("The staged artifact size is invalid.")
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ArtifactIntegrityError("The staged artifact checksum is invalid.")
            try:
                os.link(temporary, target)
                linked = True
            except FileExistsError:
                return self._existing(artifact, target, digest)
            except OSError as exc:
                raise ArtifactPersistenceError("The artifact could not be committed.") from exc
        except (ArtifactConflict, ArtifactIntegrityError, ArtifactPersistenceError):
            raise
        except OSError as exc:
            raise ArtifactPersistenceError("The artifact could not be staged.") from exc
        finally:
            temporary.unlink(missing_ok=True)

        if not linked:
            raise ArtifactPersistenceError("The artifact commit did not create an object.")
        return self._stored(artifact, target, digest)

    def read(self, artifact: StoredArtifact) -> bytes:
        path = self._storage_path(artifact.storage_key)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ArtifactPersistenceError("The artifact could not be read.") from exc
        if len(content) != artifact.size:
            raise ArtifactIntegrityError("The artifact size does not match its metadata.")
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ArtifactIntegrityError("The artifact checksum does not match its metadata.")
        return content

    def delete(self, artifact: StoredArtifact) -> None:
        path = self._storage_path(artifact.storage_key)
        try:
            path.unlink(missing_ok=True)
            self._prune_empty_parents(path.parent)
        except OSError as exc:
            raise ArtifactPersistenceError("The artifact could not be deleted.") from exc

    def _prune_empty_parents(self, directory: Path) -> None:
        run_root = self.artifact_root / "runs"
        current = directory
        while current != run_root and run_root in current.parents:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _target(self, artifact: ArtifactWrite) -> Path:
        try:
            normalized_run_id = str(UUID(artifact.run_id))
        except ValueError as exc:
            raise ArtifactPersistenceError("The artifact run ID is invalid.") from exc
        if normalized_run_id != artifact.run_id.lower():
            raise ArtifactPersistenceError("The artifact run ID is not canonical.")
        if not _SAFE_COMPONENT.fullmatch(artifact.kind):
            raise ArtifactPersistenceError("The artifact kind is invalid.")
        if (
            Path(artifact.filename).name != artifact.filename
            or artifact.filename in {".", ".."}
            or not _SAFE_COMPONENT.fullmatch(artifact.filename)
        ):
            raise ArtifactPersistenceError("The artifact filename is invalid.")
        return (
            self.artifact_root
            / "runs"
            / normalized_run_id
            / artifact.kind
            / str(artifact.schema_version)
            / artifact.filename
        )

    def _existing(
        self,
        artifact: ArtifactWrite,
        target: Path,
        expected_digest: str,
    ) -> StoredArtifact:
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise ArtifactPersistenceError("The existing artifact could not be read.") from exc
        if len(content) != len(artifact.content) or hashlib.sha256(content).hexdigest() != expected_digest:
            raise ArtifactConflict("An immutable artifact key already contains different content.")
        return self._stored(artifact, target, expected_digest)

    def _stored(
        self,
        artifact: ArtifactWrite,
        target: Path,
        digest: str,
    ) -> StoredArtifact:
        storage_key = target.relative_to(self.data_dir).as_posix()
        try:
            modified_at = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
        except OSError as exc:
            raise ArtifactPersistenceError("The committed artifact metadata could not be read.") from exc
        artifact_id = str(
            uuid5(NAMESPACE_URL, f"paperseek:{artifact.run_id}:{storage_key}:{digest}")
        )
        return StoredArtifact(
            id=artifact_id,
            run_id=artifact.run_id,
            kind=artifact.kind,
            role=artifact.role,
            visibility=artifact.visibility,
            filename=artifact.filename,
            media_type=artifact.media_type,
            storage_key=storage_key,
            sha256=digest,
            size=len(artifact.content),
            schema_version=artifact.schema_version,
            created_at=modified_at,
        )

    def _storage_path(self, storage_key: str) -> Path:
        relative = Path(storage_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ArtifactPersistenceError("The artifact storage key is invalid.")
        path = (self.data_dir / relative).resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ArtifactPersistenceError("The artifact storage key is outside the data directory.") from exc
        return path
