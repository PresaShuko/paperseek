"""Source-aware query generation and revision orchestration."""

from __future__ import annotations

from typing import Callable

from paperseek_core.prompts import (
    SYSTEM_ARXIV_QUERY_GENERATION,
    SYSTEM_ARXIV_QUERY_BROADEN,
    SYSTEM_ARXIV_QUERY_NARROW,
    SYSTEM_PAPERHUB_QUERY_GENERATION,
    SYSTEM_PAPERHUB_QUERY_BROADEN,
    SYSTEM_PAPERHUB_QUERY_NARROW,
    SYSTEM_PUBMED_QUERY_GENERATION,
    SYSTEM_PUBMED_QUERY_BROADEN,
    SYSTEM_PUBMED_QUERY_NARROW,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_BROADEN,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_NARROW,
    SYSTEM_QUERY_GENERATION,
    SYSTEM_QUERY_BROADEN,
    SYSTEM_QUERY_NARROW,
    SYSTEM_OPENALEX_QUERY_GENERATION,
    SYSTEM_OPENALEX_QUERY_BROADEN,
    SYSTEM_OPENALEX_QUERY_NARROW,
    SYSTEM_CROSSREF_QUERY_GENERATION,
    SYSTEM_CROSSREF_QUERY_BROADEN,
    SYSTEM_CROSSREF_QUERY_NARROW,
    SYSTEM_GENERIC_SOURCE_QUERY_GENERATION,
    SYSTEM_GENERIC_SOURCE_QUERY_BROADEN,
    SYSTEM_GENERIC_SOURCE_QUERY_NARROW,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_BROADEN,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_NARROW,
)


class QueryGenerationPipeline:
    """Move source-aware query prompting behind a dedicated boundary."""

    def __init__(self, host, *, starter_safe_query: Callable[[str], str]) -> None:
        self._host = host
        self._starter_safe_query = starter_safe_query

    def __getattr__(self, name):
        return getattr(self._host, name)

    def _generate_query(self, question: str) -> str:
        if self.data_source == "openalex":
            return self._generate_openalex_query(question)
        if self.data_source == "crossref":
            return self._generate_crossref_query(question)
        if self.data_source == "arxiv":
            return self._generate_source_query(
                question,
                SYSTEM_ARXIV_QUERY_GENERATION,
                "arxiv_query_generation",
                "arXiv search_query string",
            )
        if self.data_source == "semanticscholar":
            return self._generate_source_query(
                question,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
                "semanticscholar_query_generation",
                "Semantic Scholar query string",
            )
        if self.data_source == "pubmed":
            return self._generate_source_query(
                question,
                SYSTEM_PUBMED_QUERY_GENERATION,
                "pubmed_query_generation",
                "PubMed ESearch term string",
            )
        if self.data_source == "googlescholar":
            return self._generate_source_query(
                question,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
                "googlescholar_query_generation",
                "Google Scholar q string",
            )
        if self.data_source == "paperhub":
            return self._generate_source_query(
                question,
                SYSTEM_PAPERHUB_QUERY_GENERATION,
                "paperhub_query_generation",
                "PaperHub search query string",
            )
        if self.provider:
            return self._generate_generic_source_query(question)

        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nIncorporate this into the query via relevant SO= journals or TS= field-specific keywords."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('WoS query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("wos_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_QUERY_GENERATION,
            log_name="wos_query_generation",
            output_label="WoS query string",
            operation="generated query",
        )
        query = self._starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _broaden_query(self, question: str, current_query: str, feedback: str = "") -> str:
        if self.data_source == "openalex":
            messages = [
                {"role": "system", "content": SYSTEM_OPENALEX_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened OpenAlex search query string')}"
                )},
            ]
            self._llm_request_log("openalex_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log("openalex_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_OPENALEX_QUERY_BROADEN,
                log_name="openalex_query_broaden",
                output_label="broadened OpenAlex search query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "crossref":
            messages = [
                {"role": "system", "content": SYSTEM_CROSSREF_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened Crossref bibliographic query string')}"
                )},
            ]
            self._llm_request_log("crossref_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log("crossref_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_CROSSREF_QUERY_BROADEN,
                log_name="crossref_query_broaden",
                output_label="broadened Crossref bibliographic query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "arxiv":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_ARXIV_QUERY_BROADEN,
                "arxiv_query_broaden",
                "too few or zero records",
                "broadened arXiv search_query string",
                feedback,
            )
        if self.data_source == "semanticscholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_BROADEN,
                "semanticscholar_query_broaden",
                "too few or zero records",
                "broadened Semantic Scholar query string",
                feedback,
            )
        if self.data_source == "pubmed":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PUBMED_QUERY_BROADEN,
                "pubmed_query_broaden",
                "too few or zero records",
                "broadened PubMed ESearch term string",
                feedback,
            )
        if self.data_source == "googlescholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_BROADEN,
                "googlescholar_query_broaden",
                "too few or zero records",
                "broadened Google Scholar q string",
                feedback,
            )
        if self.data_source == "paperhub":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PAPERHUB_QUERY_BROADEN,
                "paperhub_query_broaden",
                "too few or zero records",
                "broadened PaperHub search query string",
                feedback,
            )
        if self.provider:
            messages = [
                {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Source: {self._source_label()}\n"
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened plain search query string')}"
                )},
            ]
            self._llm_request_log(f"{self.data_source}_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log(f"{self.data_source}_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_BROADEN,
                log_name=f"{self.data_source}_query_broaden",
                output_label="broadened plain search query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_BROADEN},
            {"role": "user", "content": (
                f"Question: {question}\n"
                f"{self._intent_context()}"
                f"{self._discipline_context()}\n"
                f"{feedback}"
                f"Current query returned too few or zero results: {current_query}\n"
                f"{self._strict_query_output_instruction('broadened WoS query string')}"
            )},
        ]
        self._llm_request_log("wos_query_broaden")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_broaden")
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=SYSTEM_QUERY_BROADEN,
            log_name="wos_query_broaden",
            output_label="broadened WoS query string",
            operation="broadened query",
        )
        query = self._starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _narrow_query(self, question: str, current_query: str, feedback: str = "") -> str:
        if self.data_source == "openalex":
            messages = [
                {"role": "system", "content": SYSTEM_OPENALEX_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed OpenAlex search query string')}"
                )},
            ]
            self._llm_request_log("openalex_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log("openalex_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_OPENALEX_QUERY_NARROW,
                log_name="openalex_query_narrow",
                output_label="narrowed OpenAlex search query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "crossref":
            messages = [
                {"role": "system", "content": SYSTEM_CROSSREF_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed Crossref bibliographic query string')}"
                )},
            ]
            self._llm_request_log("crossref_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log("crossref_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_CROSSREF_QUERY_NARROW,
                log_name="crossref_query_narrow",
                output_label="narrowed Crossref bibliographic query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "arxiv":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_ARXIV_QUERY_NARROW,
                "arxiv_query_narrow",
                "too many records",
                "narrowed arXiv search_query string",
                feedback,
            )
        if self.data_source == "semanticscholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_NARROW,
                "semanticscholar_query_narrow",
                "too many records",
                "narrowed Semantic Scholar query string",
                feedback,
            )
        if self.data_source == "pubmed":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PUBMED_QUERY_NARROW,
                "pubmed_query_narrow",
                "too many records",
                "narrowed PubMed ESearch term string",
                feedback,
            )
        if self.data_source == "googlescholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_NARROW,
                "googlescholar_query_narrow",
                "too many records",
                "narrowed Google Scholar q string",
                feedback,
            )
        if self.data_source == "paperhub":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PAPERHUB_QUERY_NARROW,
                "paperhub_query_narrow",
                "too many records",
                "narrowed PaperHub search query string",
                feedback,
            )
        if self.provider:
            messages = [
                {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Source: {self._source_label()}\n"
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed plain search query string')}"
                )},
            ]
            self._llm_request_log(f"{self.data_source}_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log(f"{self.data_source}_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_NARROW,
                log_name=f"{self.data_source}_query_narrow",
                output_label="narrowed plain search query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query

        field_hint = ""
        if self.config.search_field:
            field_hint = f" Consider adding SO= for key journals in {self.config.search_field}."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_NARROW},
            {"role": "user", "content": (
                f"Question: {question}\n"
                f"{self._intent_context()}"
                f"Current query returned too many results: {current_query}\n"
                f"{feedback}"
                f"{field_hint}\n"
                f"{self._strict_query_output_instruction('narrowed WoS query string')}"
            )},
        ]
        self._llm_request_log("wos_query_narrow")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_narrow")
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=SYSTEM_QUERY_NARROW,
            log_name="wos_query_narrow",
            output_label="narrowed WoS query string",
            operation="narrowed query",
        )
        query = self._starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_openalex_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English field or topic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_OPENALEX_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('OpenAlex search query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("openalex_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("openalex_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_OPENALEX_QUERY_GENERATION,
            log_name="openalex_query_generation",
            output_label="OpenAlex search query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_generic_source_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English academic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_GENERATION},
            {"role": "user", "content": (
                f"Source: {self._source_label()}\n"
                f"Research question: {question}{context}{field_hint}\n\n"
                f"{self._strict_query_output_instruction('source search query string')}"
            )},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log(f"{self.data_source}_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log(f"{self.data_source}_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_GENERATION,
            log_name=f"{self.data_source}_query_generation",
            output_label="source search query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_source_query(self, question: str, system_prompt: str, log_name: str, output_label: str) -> str:
        context = self._intent_context()
        field_context = self._discipline_context()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research question: {question}{context}{field_context}{self._strict_query_output_instruction(output_label)}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log(log_name)
        raw = self._chat_query_json(messages)
        self._llm_response_log(log_name)
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _revise_source_query(
        self,
        question: str,
        current_query: str,
        system_prompt: str,
        log_name: str,
        result_description: str,
        output_label: str,
        feedback: str = "",
    ) -> str:
        context = self._intent_context()
        field_context = self._discipline_context()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Source: {self._source_label()}\n"
                f"Question: {question}\n"
                f"{context}"
                f"{field_context}\n"
                f"{feedback}"
                f"Current query returned {result_description}: {current_query}\n"
                f"{self._strict_query_output_instruction(output_label)}"
            )},
        ]
        self._llm_request_log(log_name)
        raw = self._chat_query_json(messages)
        self._llm_response_log(log_name)
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation="revised query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_crossref_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English bibliographic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_CROSSREF_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('Crossref bibliographic query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("crossref_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("crossref_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_CROSSREF_QUERY_GENERATION,
            log_name="crossref_query_generation",
            output_label="Crossref bibliographic query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query
