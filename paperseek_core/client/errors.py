"""Exceptions exposed by PaperSeek's WoS Starter adapter."""

from __future__ import annotations

from typing import Any, Optional


class OpenApiException(Exception):
    pass


class ApiTypeError(OpenApiException, TypeError):
    pass


class ApiValueError(OpenApiException, ValueError):
    pass


class ApiAttributeError(OpenApiException, AttributeError):
    pass


class ApiKeyError(OpenApiException, KeyError):
    pass


class ApiException(OpenApiException):
    def __init__(
        self,
        status: Optional[int] = None,
        reason: Optional[str] = None,
        *,
        http_resp: Any = None,
        body: Optional[str] = None,
        data: Any = None,
    ) -> None:
        if http_resp is not None:
            status = status if status is not None else getattr(http_resp, "status_code", getattr(http_resp, "status", None))
            reason = reason or getattr(http_resp, "reason", None)
            body = body if body is not None else getattr(http_resp, "text", None)
        self.status = status
        self.reason = reason or "WoS Starter request failed"
        self.body = body
        self.data = data
        self.headers = getattr(http_resp, "headers", None) if http_resp is not None else None
        super().__init__(self.__str__())

    def __str__(self) -> str:
        prefix = f"({self.status}) " if self.status is not None else ""
        message = f"{prefix}{self.reason}"
        if self.body:
            message = f"{message}\nResponse body: {self.body}"
        return message


class BadRequestException(ApiException):
    pass


class UnauthorizedException(ApiException):
    pass


class ForbiddenException(ApiException):
    pass


class NotFoundException(ApiException):
    pass


class ServiceException(ApiException):
    pass
