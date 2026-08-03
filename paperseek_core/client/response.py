"""HTTP response wrapper used by compatibility methods."""

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, TypeVar


T = TypeVar("T")


@dataclass
class ApiResponse(Generic[T]):
    data: Optional[T] = None
    status_code: Optional[int] = None
    headers: Dict[str, Any] = field(default_factory=dict)
    raw_data: Optional[bytes] = None
