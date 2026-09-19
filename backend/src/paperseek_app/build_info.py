"""Build identity embedded in the Community distribution."""

from __future__ import annotations


DISTRIBUTION = "paperseek"
VERSION = "0.3.0"
COMMUNITY_COMMIT = "source-tree"
PUBLIC_OPENAPI_SHA256 = "4F5A00AB1C0144504BEA4E6C2F22B6E9980954ADFD745AF6CDA7DA9EB2AB34BA"
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
