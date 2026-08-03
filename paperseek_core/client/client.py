"""HTTP transport for PaperSeek's independently implemented WoS adapter."""

from __future__ import annotations

from typing import Dict, Optional

import requests

from paperseek_core.client.config import Configuration
from paperseek_core.client.errors import ApiException


class ApiClient:
    _default: Optional["ApiClient"] = None

    def __init__(
        self,
        configuration: Optional[Configuration] = None,
        header_name: Optional[str] = None,
        header_value: Optional[str] = None,
        cookie: Optional[str] = None,
    ) -> None:
        self.configuration = configuration or Configuration.get_default_copy()
        self.default_headers: Dict[str, str] = {"Accept": "application/json"}
        if header_name and header_value:
            self.default_headers[str(header_name)] = str(header_value)
        if cookie:
            self.default_headers["Cookie"] = str(cookie)
        self.session = requests.Session()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    @property
    def user_agent(self) -> str:
        return self.default_headers.get("User-Agent", "paperseek-wos-client/0.3")

    @user_agent.setter
    def user_agent(self, value: str) -> None:
        self.default_headers["User-Agent"] = value

    def set_default_header(self, header_name: str, header_value: str) -> None:
        self.default_headers[str(header_name)] = str(header_value)

    @classmethod
    def get_default(cls) -> "ApiClient":
        if cls._default is None:
            cls._default = cls()
        return cls._default

    @classmethod
    def set_default(cls, default: "ApiClient") -> None:
        if not isinstance(default, cls):
            raise TypeError("default must be an ApiClient instance")
        cls._default = default

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        request_headers = dict(self.default_headers)
        request_headers["User-Agent"] = self.user_agent
        api_key = self.configuration.get_api_key_with_prefix("ClarivateApiKeyAuth")
        if api_key:
            request_headers["X-ApiKey"] = api_key
        request_headers.update({str(key): str(value) for key, value in (headers or {}).items()})
        url = f"{self.configuration.host}/{str(path).lstrip('/')}"
        try:
            response = self.session.request(
                method.upper(),
                url,
                params=params,
                headers=request_headers,
                timeout=timeout or self.configuration.timeout,
                verify=self.configuration.verify_ssl,
            )
        except requests.RequestException as exc:
            raise ApiException(reason=f"WoS Starter network error: {exc}") from exc
        if not 200 <= response.status_code < 300:
            raise ApiException(http_resp=response)
        return response
