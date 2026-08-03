"""WoS Starter document endpoints used by PaperSeek."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

from paperseek_core.client.client import ApiClient
from paperseek_core.client.errors import ApiException
from paperseek_core.client.models import Document, DocumentsList
from paperseek_core.client.response import ApiResponse


Timeout = Optional[Union[float, Tuple[float, float]]]


class DocumentsApi:
    def __init__(self, api_client: Optional[ApiClient] = None) -> None:
        self.api_client = api_client or ApiClient.get_default()

    @staticmethod
    def _limit(value: Optional[int]) -> int:
        limit = 10 if value is None else int(value)
        if limit < 1:
            raise ValueError("WoS Starter limit must be positive")
        return min(limit, 50)

    @staticmethod
    def _decode(response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiException(
                status=response.status_code,
                reason="WoS Starter returned invalid JSON",
                body=response.text,
            ) from exc
        if not isinstance(payload, dict):
            raise ApiException(
                status=response.status_code,
                reason="WoS Starter returned a non-object JSON payload",
                body=response.text,
            )
        return payload

    def _documents_response(
        self,
        *,
        q: str,
        db: Optional[str],
        limit: Optional[int],
        page: Optional[int],
        sort_field: Optional[str],
        modified_time_span: Optional[str],
        tc_modified_time_span: Optional[str],
        detail: Optional[str],
        timeout: Timeout,
        headers: Optional[Dict[str, Any]],
    ):
        if not str(q or "").strip():
            raise ValueError("q is required")
        params = {
            "q": str(q),
            "db": db,
            "limit": self._limit(limit),
            "page": page,
            "sortField": sort_field,
            "modifiedTimeSpan": modified_time_span,
            "tcModifiedTimeSpan": tc_modified_time_span,
            "detail": detail,
        }
        return self.api_client.request(
            "GET",
            "/documents",
            params={key: value for key, value in params.items() if value is not None},
            headers=headers,
            timeout=timeout,
        )

    def documents_get(
        self,
        q: str,
        db: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_field: Optional[str] = None,
        modified_time_span: Optional[str] = None,
        tc_modified_time_span: Optional[str] = None,
        detail: Optional[str] = None,
        _request_timeout: Timeout = None,
        _request_auth: Optional[Dict[str, Any]] = None,
        _content_type: Optional[str] = None,
        _headers: Optional[Dict[str, Any]] = None,
        _host_index: int = 0,
    ) -> DocumentsList:
        del _request_auth, _content_type, _host_index
        response = self._documents_response(
            q=q,
            db=db,
            limit=limit,
            page=page,
            sort_field=sort_field,
            modified_time_span=modified_time_span,
            tc_modified_time_span=tc_modified_time_span,
            detail=detail,
            timeout=_request_timeout,
            headers=_headers,
        )
        return DocumentsList.from_dict(self._decode(response))

    def documents_get_with_http_info(self, *args, **kwargs) -> ApiResponse[DocumentsList]:
        q = kwargs.pop("q", args[0] if args else None)
        response = self._documents_response(
            q=q,
            db=kwargs.pop("db", None),
            limit=kwargs.pop("limit", None),
            page=kwargs.pop("page", None),
            sort_field=kwargs.pop("sort_field", None),
            modified_time_span=kwargs.pop("modified_time_span", None),
            tc_modified_time_span=kwargs.pop("tc_modified_time_span", None),
            detail=kwargs.pop("detail", None),
            timeout=kwargs.pop("_request_timeout", None),
            headers=kwargs.pop("_headers", None),
        )
        data = DocumentsList.from_dict(self._decode(response))
        return ApiResponse(data=data, status_code=response.status_code, headers=dict(response.headers), raw_data=response.content)

    def documents_get_without_preload_content(self, *args, **kwargs):
        q = kwargs.pop("q", args[0] if args else None)
        return self._documents_response(
            q=q,
            db=kwargs.pop("db", None),
            limit=kwargs.pop("limit", None),
            page=kwargs.pop("page", None),
            sort_field=kwargs.pop("sort_field", None),
            modified_time_span=kwargs.pop("modified_time_span", None),
            tc_modified_time_span=kwargs.pop("tc_modified_time_span", None),
            detail=kwargs.pop("detail", None),
            timeout=kwargs.pop("_request_timeout", None),
            headers=kwargs.pop("_headers", None),
        )

    def _document_uid_response(self, uid: str, *, db: Optional[str], timeout: Timeout, headers: Optional[dict]):
        if not str(uid or "").strip():
            raise ValueError("uid is required")
        params = {"db": db} if db else None
        return self.api_client.request(
            "GET",
            f"/documents/{str(uid).strip()}",
            params=params,
            headers=headers,
            timeout=timeout,
        )

    def documents_uid_get(
        self,
        uid: str,
        db: Optional[str] = None,
        _request_timeout: Timeout = None,
        _request_auth: Optional[Dict[str, Any]] = None,
        _content_type: Optional[str] = None,
        _headers: Optional[Dict[str, Any]] = None,
        _host_index: int = 0,
    ) -> Document:
        del _request_auth, _content_type, _host_index
        response = self._document_uid_response(uid, db=db, timeout=_request_timeout, headers=_headers)
        payload = self._decode(response)
        if isinstance(payload.get("hits"), list):
            payload = payload["hits"][0] if payload["hits"] else {}
        return Document.from_dict(payload)

    def documents_uid_get_with_http_info(self, *args, **kwargs) -> ApiResponse[Document]:
        uid = kwargs.pop("uid", args[0] if args else None)
        response = self._document_uid_response(
            uid,
            db=kwargs.pop("db", None),
            timeout=kwargs.pop("_request_timeout", None),
            headers=kwargs.pop("_headers", None),
        )
        payload = self._decode(response)
        if isinstance(payload.get("hits"), list):
            payload = payload["hits"][0] if payload["hits"] else {}
        data = Document.from_dict(payload)
        return ApiResponse(data=data, status_code=response.status_code, headers=dict(response.headers), raw_data=response.content)

    def documents_uid_get_without_preload_content(self, *args, **kwargs):
        uid = kwargs.pop("uid", args[0] if args else None)
        return self._document_uid_response(
            uid,
            db=kwargs.pop("db", None),
            timeout=kwargs.pop("_request_timeout", None),
            headers=kwargs.pop("_headers", None),
        )
