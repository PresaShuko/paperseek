"""Compatibility exports for callers of the former generated transport."""

from __future__ import annotations

from typing import Optional

import requests


RESTResponseType = requests.Response


class RESTClientObject:
    def __init__(self, configuration) -> None:
        from paperseek_core.client.client import ApiClient

        self.api_client = ApiClient(configuration=configuration)

    def request(
        self,
        method: str,
        url: str,
        query_params: Optional[dict] = None,
        headers: Optional[dict] = None,
        _request_timeout=None,
        **_: object,
    ) -> requests.Response:
        host = self.api_client.configuration.host.rstrip("/")
        path = url[len(host):] if str(url).startswith(host) else url
        return self.api_client.request(
            method,
            path,
            params=query_params,
            headers=headers,
            timeout=_request_timeout,
        )
