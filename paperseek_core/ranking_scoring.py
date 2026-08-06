"""LLM request protocol for ranking scores and retained-paper reasons."""

import re
from typing import Any, Callable

from paperseek_core.prompts import SYSTEM_RESULT_RANKING
from paperseek_core.ranking import EmptyRankingBatchError


class RankingScorer:
    def __init__(self, host: Any, describe_document: Callable[..., str]):
        self.host = host
        self.describe_document = describe_document

    def score_batch(self, question: str, documents: list, llm_client: Any) -> list:
        host = self.host
        host._emit_log(f"Global score-only ranking started: candidates={len(documents)}.")
        try:
            scores = self.request_compact_scores(question, documents, llm_client)
        except Exception as exc:
            if not self.should_retry_in_chunks(exc):
                raise
            host._emit_log(
                "Global score-only ranking failed; retrying in 64-candidate score-only chunks: "
                f"{type(exc).__name__}: {exc}"
            )
            scores = self.request_scores_in_chunks(question, documents, llm_client)
        matched, missing = host._match_ranking_scores_to_documents(documents, scores)
        if missing:
            host._emit_log(
                f"Global score-only ranking omitted {len(missing)}/{len(documents)} candidate(s); "
                "retrying in 64-candidate score-only chunks."
            )
            scores = self.request_scores_in_chunks(question, documents, llm_client)
            matched, missing = host._match_ranking_scores_to_documents(documents, scores)
            if missing:
                raise EmptyRankingBatchError(
                    f"Chunked score-only ranking omitted {len(missing)}/{len(documents)} candidate(s)."
                )
        host._emit_log(f"Global score-only ranking completed: scored={len(matched)}.")
        return matched

    def attach_reasons(self, question: str, documents: list, scores: list, llm_client: Any) -> list:
        host = self.host
        reason_documents = self.reason_documents(documents, scores)
        reason_by_uid = {}
        if reason_documents:
            host._emit_log(
                f"Ranking reason generation started for {len(reason_documents)} retained candidate(s)."
            )
        for start in range(0, len(reason_documents), 64):
            batch = reason_documents[start:start + 64]
            try:
                reason_by_uid.update(self.request_reasons(question, batch, scores, llm_client))
            except Exception as exc:
                host._emit_log(
                    "Ranking reason generation failed for retained candidates; keeping global scores: "
                    f"{type(exc).__name__}: {exc}"
                )
        for entry in scores:
            entry["reasoning"] = reason_by_uid.get(str(entry.get("uid") or ""), "")
        return scores

    @staticmethod
    def should_retry_in_chunks(exc: Exception) -> bool:
        text = str(exc or "").casefold()
        if "429" in text or "rate_limit" in text or "too many requests" in text:
            return False
        return any(
            marker in text
            for marker in (
                "context length",
                "context_length",
                "maximum context",
                "max token",
                "too many tokens",
                "truncat",
                "json",
                "message content",
                "did not contain",
                "empty response",
                "timed out",
                "timeout",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "api error (500)",
                "api error (502)",
                "api error (503)",
                "api error (504)",
                "upstream transport failure",
                "upstream proxy failed",
                "proxy_error",
                "network error",
                "connection reset",
            )
        )

    def request_compact_scores(self, question: str, documents: list, llm_client: Any) -> list:
        descriptions = []
        for index, document in enumerate(documents, 1):
            description = self.describe_document(document, index, abstract_limit=500)
            descriptions.append(re.sub(rf"^{index}\. UID:.*$", f"{index}.", description, count=1, flags=re.MULTILINE))
        papers_text = "\n\n".join(descriptions)
        messages = [
            {"role": "system", "content": SYSTEM_RESULT_RANKING},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{self.host._ranking_plan_context()}\n\n"
                    f"Papers:\n\n{papers_text}\n\n"
                    'Return only {"scores":[[index,score],...]} with one pair for every index.'
                ),
            },
        ]
        chat_json = getattr(llm_client, "chat_json", None)
        raw = self.host._run_cancellable(
            lambda: (
                chat_json(messages, temperature=0.0, max_tokens=4096)
                if callable(chat_json)
                else llm_client.chat(messages, temperature=0.0)
            )
        )
        return self.host._parse_compact_ranking_scores(raw, documents)

    def request_scores_in_chunks(
        self,
        question: str,
        documents: list,
        llm_client: Any,
        chunk_size: int = 64,
    ) -> list:
        scores = []
        for start in range(0, len(documents), chunk_size):
            batch = documents[start:start + chunk_size]
            batch_scores = self.request_compact_scores(question, batch, llm_client)
            matched, missing = self.host._match_ranking_scores_to_documents(batch, batch_scores)
            if missing:
                raise EmptyRankingBatchError(
                    f"Score-only chunk {start // chunk_size + 1} omitted {len(missing)}/{len(batch)} candidate(s)."
                )
            scores.extend(matched)
        return scores

    def reason_documents(self, documents: list, scores: list) -> list:
        identity = self.host._ranking_document_identity
        score_by_uid = {str(entry.get("uid") or ""): float(entry.get("score") or 0) for entry in scores}
        ordered = sorted(documents, key=lambda document: score_by_uid.get(identity(document), 0), reverse=True)
        if len(ordered) < 50:
            return ordered
        high_scores = [document for document in ordered if score_by_uid.get(identity(document), 0) >= 5]
        return high_scores if len(high_scores) > 50 else ordered[:50]

    def request_reasons(self, question: str, documents: list, scores: list, llm_client: Any) -> dict[str, str]:
        identity = self.host._ranking_document_identity
        score_by_uid = {str(entry.get("uid") or ""): entry.get("score", 0) for entry in scores}
        descriptions = []
        identities = []
        for index, document in enumerate(documents, 1):
            document_identity = identity(document)
            identities.append(document_identity)
            description = self.describe_document(document, index, abstract_limit=700)
            descriptions.append(
                re.sub(
                    rf"^{index}\. UID:.*$",
                    f"{index}. Score: {score_by_uid.get(document_identity, 0)}",
                    description,
                    count=1,
                    flags=re.MULTILINE,
                )
            )
        retained_text = "\n\n".join(descriptions)
        messages = [
            {
                "role": "system",
                "content": (
                    "Explain the supplied relevance scores using only the paper metadata and stable SearchPlan. "
                    "Give one concise evidence-based sentence in the user's language for every integer index. "
                    "Prioritize topical fit; mention a venue credibility adjustment only when it materially affected the score and the venue reputation is known with high confidence. "
                    "Do not infer poor quality from open-access status, publisher, impact factor, quartile, or citation count alone. "
                    'Output only JSON shaped as {"reasons":[[1,"reason"],[2,"reason"]]}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{self.host._ranking_plan_context()}\n\n"
                    f"Retained papers:\n\n{retained_text}\n\n"
                    'Return only {"reasons":[[index,"reason"],...]}.'
                ),
            },
        ]
        chat_json = getattr(llm_client, "chat_json", None)
        max_tokens = min(8192, max(2048, len(documents) * 96))
        raw = self.host._run_cancellable(
            lambda: (
                chat_json(messages, temperature=0.0, max_tokens=max_tokens)
                if callable(chat_json)
                else llm_client.chat(messages, temperature=0.0)
            )
        )
        return self.host._parse_ranking_reasons(raw, identities)
