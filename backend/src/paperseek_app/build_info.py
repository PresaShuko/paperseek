"""Build identity embedded in the Community distribution."""

from __future__ import annotations


DISTRIBUTION = "paperseek"
VERSION = "1.0.0b1"
COMMUNITY_COMMIT = "source-tree"
PUBLIC_OPENAPI_SHA256 = "E24266DC6C60814AB571DC1E0CEF16DD6E9B703B14F7F211B40C86186825F355"
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
