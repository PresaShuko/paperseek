"""Build identity embedded in the M2 Community distribution."""

from __future__ import annotations


DISTRIBUTION = "paperseek"
VERSION = "0.3.0"
COMMUNITY_COMMIT = "5525a58bd72e5f1cd18b681a25d0eea72e6b24ef"
PUBLIC_OPENAPI_SHA256 = "B434FA1CFD36B5BC7D6E9CEB9EFF725B41BCF1500C9D8ED773BA53F03E435062"
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
