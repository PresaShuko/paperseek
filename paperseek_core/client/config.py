"""Configuration for PaperSeek's minimal WoS Starter adapter."""

from __future__ import annotations

import copy
from typing import Dict, Optional


class Configuration:
    _default: Optional["Configuration"] = None

    def __init__(
        self,
        host: str = "https://api.clarivate.com/apis/wos-starter/v1",
        api_key: Optional[Dict[str, str]] = None,
        api_key_prefix: Optional[Dict[str, str]] = None,
        *,
        verify_ssl: bool = True,
        timeout: float = 45.0,
        **_: object,
    ) -> None:
        self.host = str(host or "https://api.clarivate.com/apis/wos-starter/v1").rstrip("/")
        self.api_key = dict(api_key or {})
        self.api_key_prefix = dict(api_key_prefix or {})
        self.verify_ssl = bool(verify_ssl)
        self.timeout = float(timeout)

    def __deepcopy__(self, memo):
        copied = type(self)(
            host=self.host,
            api_key=copy.deepcopy(self.api_key, memo),
            api_key_prefix=copy.deepcopy(self.api_key_prefix, memo),
            verify_ssl=self.verify_ssl,
            timeout=self.timeout,
        )
        memo[id(self)] = copied
        return copied

    @classmethod
    def set_default(cls, default: "Configuration") -> None:
        if not isinstance(default, cls):
            raise TypeError("default must be a Configuration instance")
        cls._default = default

    @classmethod
    def get_default(cls) -> "Configuration":
        if cls._default is None:
            cls._default = cls()
        return cls._default

    @classmethod
    def get_default_copy(cls) -> "Configuration":
        return copy.deepcopy(cls.get_default())

    def get_api_key_with_prefix(self, identifier: str, alias: Optional[str] = None) -> Optional[str]:
        key = self.api_key.get(identifier) or (self.api_key.get(alias) if alias else None)
        if not key:
            return None
        prefix = self.api_key_prefix.get(identifier) or (self.api_key_prefix.get(alias) if alias else None)
        return f"{prefix} {key}" if prefix else key

    def auth_settings(self) -> dict:
        return {
            "ClarivateApiKeyAuth": {
                "type": "api_key",
                "in": "header",
                "key": "X-ApiKey",
                "value": self.get_api_key_with_prefix("ClarivateApiKeyAuth"),
            }
        }

    def to_debug_report(self) -> str:
        return f"PaperSeek WoS client host={self.host} verify_ssl={self.verify_ssl}"
