"""TypeSafe and SiliconFlow SystemOne wire protocol (no SDK dependency)."""
from __future__ import annotations

from paperseek_core.models import DecisionBatchResult, DecisionScore
from paperseek_core.http_retry import MODEL_ATTEMPTS
from paperseek_core.sources.http import AsyncHttpTransport, TRANSIENT_STATUSES


class SystemOneAdapter:
    def __init__(self, transport: AsyncHttpTransport, *, provider: str, model: str,
                 base_url: str, api_key: str) -> None:
        self.transport = transport
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def score(self, state: dict, questions: dict) -> DecisionBatchResult:
        if not self.api_key.strip():
            raise ValueError("A decision-model credential is required.")
        response, _ = await self.transport.request(
            self.provider, "POST", f"{self.base_url}/systemone",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "state": state, "questions": questions},
            timeout=60, attempts=MODEL_ATTEMPTS, retry_statuses=TRANSIENT_STATUSES,
        )
        response.raise_for_status()
        body = response.json()
        answers = body.get("answers")
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise ValueError("Decision answers must match every candidate exactly once.")
        scores = {}
        for key, answer in answers.items():
            if not isinstance(answer, dict) or answer.get("type") != "score":
                raise ValueError("Decision answers must use the Score primitive.")
            scores[key] = DecisionScore.model_validate({
                "score": answer.get("score"), "confidence": answer.get("confidence"),
            })
        usage = body.get("usage") or {}
        return DecisionBatchResult(
            scores=scores, model=body.get("model") or self.model,
            input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
        )
