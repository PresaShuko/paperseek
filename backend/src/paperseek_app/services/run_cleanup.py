from __future__ import annotations

from datetime import timedelta

from paperseek_app.errors import ArtifactError
from paperseek_app.models import DeletionReceipt
from paperseek_app.ports import ArtifactStore, RunUnitOfWork


class RunCleanupService:
    def __init__(self, uow: RunUnitOfWork, artifact_store: ArtifactStore) -> None:
        self.uow = uow
        self.artifact_store = artifact_store

    def delete_history_run(self, run_id: str) -> DeletionReceipt:
        return self.uow.stage_run_deletion(run_id)

    def cleanup_next_deleted_run(
        self,
        owner_id: str,
        *,
        lease_seconds: int = 60,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("A cleanup lease must be positive.")
        lease = self.uow.claim_cleanup_job(owner_id, timedelta(seconds=lease_seconds))
        if lease is None:
            return False
        try:
            for artifact in self.uow.list_cleanup_artifacts(lease):
                self.artifact_store.delete(artifact)
        except ArtifactError:
            self.uow.fail_cleanup(lease, "artifact_delete_failed")
            return True
        self.uow.complete_cleanup(lease)
        return True
