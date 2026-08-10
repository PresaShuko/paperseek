"""Shared application package boundary for the v0.3.0 cutover."""

from paperseek_core import __version__
from paperseek_app.services import RunService

__all__ = ["RunService", "__version__"]
