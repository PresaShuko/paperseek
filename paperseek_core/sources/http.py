from typing import Any, Dict, List, Optional
import re
import time

import requests

from paperseek_core.sources.contracts import ProviderError


def redact_request_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return re.sub(
        r"([?&](?:api_key|apikey|key|token|access_token)=)[^&\s)]+",
        r"\1<redacted>",
        text,
        flags=re.I,
    )


def get_with_retries(
    source: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    query: str = "",
    attempts: int = 3,
):
    last_exc: Optional[requests.RequestException] = None
    started = time.perf_counter()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            info = {
                "method": "GET",
                "url": redact_request_text(response.url),
                "status": response.status_code,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempt,
            }
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                time.sleep(retry_delay(response, attempt, source))
                continue
            return response, info
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(0.7 * attempt)

    info = {
        "method": "GET",
        "url": url,
        "status": "request_error",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "attempts": attempts,
    }
    detail = redact_request_text(last_exc)
    raise ProviderError(
        source,
        f"{source.title()} request failed after {attempts} attempts: {detail}",
        query=query,
    ) from last_exc


def split_api_keys(value: str) -> List[str]:
    return list(dict.fromkeys(item.strip() for item in re.split(r"[\s,;]+", value or "") if item.strip()))


def retry_delay(response: requests.Response, attempt: int, source: str = "") -> float:
    retry_after = response.headers.get("Retry-After", "")
    try:
        return max(0.7 * attempt, min(float(retry_after), 15.0))
    except (TypeError, ValueError):
        if response.status_code == 429 and (source or "").lower() == "arxiv":
            return min(5.0 * attempt, 20.0)
        if response.status_code == 429 and (source or "").lower() == "semanticscholar":
            return min(2.0 * attempt, 8.0)
        return 0.7 * attempt
