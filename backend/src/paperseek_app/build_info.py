"""Build identity embedded in the Community distribution."""

from __future__ import annotations


DISTRIBUTION = "paperseek"
VERSION = "0.3.0"
COMMUNITY_COMMIT = "source-tree"
PUBLIC_OPENAPI_SHA256 = "F9BBBA3681D4CF288093B87FCFE72A14CBD0161815C81C1349174CC926F6C62D"
SOURCE_TREE_DIRTY = True


def as_dict() -> dict[str, str | bool]:
    return {
        "distribution": DISTRIBUTION,
        "version": VERSION,
        "community_commit": COMMUNITY_COMMIT,
        "public_openapi_sha256": PUBLIC_OPENAPI_SHA256,
        "source_tree_dirty": SOURCE_TREE_DIRTY,
    }


__all__ = [
    "COMMUNITY_COMMIT",
    "DISTRIBUTION",
    "PUBLIC_OPENAPI_SHA256",
    "SOURCE_TREE_DIRTY",
    "VERSION",
    "as_dict",
]
