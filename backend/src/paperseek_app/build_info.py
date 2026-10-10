"""Build identity embedded in the Community distribution."""

from __future__ import annotations


DISTRIBUTION = "paperseek"
VERSION = "1.0.0b1"
COMMUNITY_COMMIT = "source-tree"
PUBLIC_OPENAPI_SHA256 = "1641AFE6DCD25F3F88875EBA39EDF9FE4836871C982BB8B601A67E4B344BB360"
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
