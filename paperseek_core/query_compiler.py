import re
from dataclasses import dataclass
from typing import Protocol

from paperseek_core.harness.query_contract import validate_source_query
from paperseek_core.planning import ConceptGroup, QueryView


@dataclass(frozen=True)
class CompiledQuery:
    source: str
    view_id: str
    query: str
    purpose: str = ""


class QueryCompiler(Protocol):
    SOURCE: str

    def compile(self, view: QueryView) -> CompiledQuery: ...


def _selected_groups(view: QueryView) -> list[ConceptGroup]:
    required = [group for group in view.concept_groups if group.required]
    return required or list(view.concept_groups[:1])


def _clean_term(value: str, *, strip_wildcards: bool = True) -> str:
    term = re.sub(r"\s+", " ", str(value or "")).strip()
    term = term.replace("\\", " ").replace('"', " ")
    if strip_wildcards:
        term = term.replace("*", "").replace("?", "")
    term = re.sub(r"\s+", " ", term).strip(" ()[]{}")
    return term


def _quoted_term(value: str) -> str:
    term = _clean_term(value)
    if not term:
        return ""
    return f'"{term}"' if re.search(r"\s", term) else term


def _unique_terms(groups: list[ConceptGroup], *, per_group: int = 4, total: int = 12) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group.terms[:per_group]:
            term = _clean_term(value)
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            output.append(term)
            if len(output) >= total:
                return output
    return output


class ArxivQueryCompiler:
    SOURCE = "arxiv"
    FIELD_MAP = {"all": "all", "title": "ti", "abstract": "abs"}

    def compile(self, view: QueryView) -> CompiledQuery:
        required: list[str] = []
        optional: list[str] = []
        for group in view.concept_groups:
            clause = self._compile_group(group)
            if not clause:
                continue
            (required if group.required else optional).append(clause)
        clauses = list(required)
        if not clauses and optional:
            clauses = [optional[0] if len(optional) == 1 else f"({' OR '.join(optional)})"]
        if not clauses:
            raise ValueError("arXiv query view did not contain compilable terms")
        query = " AND ".join(clauses)
        for exclusion in view.exclusions:
            term = self._compile_term(exclusion, "all")
            if term:
                query += f" ANDNOT {term}"
        validation = validate_source_query(self.SOURCE, query)
        if not validation.ok:
            raise ValueError(validation.issue)
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    def _compile_group(self, group: ConceptGroup) -> str:
        field = self.FIELD_MAP.get(group.field_hint, "all")
        terms = [self._compile_term(term, field) for term in group.terms]
        terms = [term for term in terms if term]
        if not terms:
            return ""
        if len(terms) == 1:
            return terms[0]
        return f"({' OR '.join(terms)})"

    @staticmethod
    def _compile_term(value: str, field: str) -> str:
        term = re.sub(r"\s+", " ", str(value or "")).strip()
        term = term.replace("\\", " ").replace('"', " ")
        term = re.sub(r"\s+", " ", term).strip(" ()")
        if not term:
            return ""
        if re.search(r"\s", term):
            return f'{field}:"{term}"'
        return f"{field}:{term}"


class OpenAlexQueryCompiler:
    SOURCE = "openalex"

    def compile(self, view: QueryView) -> CompiledQuery:
        required: list[str] = []
        optional: list[str] = []
        for group in view.concept_groups:
            clause = self._compile_group(group)
            if not clause:
                continue
            (required if group.required else optional).append(clause)
        clauses = list(required)
        if not clauses and optional:
            clauses = [optional[0] if len(optional) == 1 else f"({' OR '.join(optional)})"]
        if not clauses:
            raise ValueError("OpenAlex query view did not contain compilable terms")
        query = " AND ".join(clauses)
        for exclusion in view.exclusions:
            term = self._compile_term(exclusion)
            if term:
                query += f" NOT {term}"
        validation = validate_source_query(self.SOURCE, query)
        if not validation.ok:
            raise ValueError(validation.issue)
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    def _compile_group(self, group: ConceptGroup) -> str:
        terms = [self._compile_term(term) for term in group.terms]
        terms = [term for term in terms if term]
        if not terms:
            return ""
        if len(terms) == 1:
            return terms[0]
        return f"({' OR '.join(terms)})"

    @staticmethod
    def _compile_term(value: str) -> str:
        term = _clean_term(value)
        if not term:
            return ""
        return f'"{term}"' if re.search(r"\s", term) else term


class CrossrefQueryCompiler:
    SOURCE = "crossref"

    def compile(self, view: QueryView) -> CompiledQuery:
        terms = _unique_terms(_selected_groups(view))
        if not terms:
            raise ValueError("Crossref query view did not contain compilable terms")
        query = " ".join(terms)
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)


class SemanticScholarQueryCompiler:
    SOURCE = "semanticscholar"

    def compile(self, view: QueryView) -> CompiledQuery:
        # PaperSeek's relevance lane uses /paper/search, whose query is plain
        # title/abstract text. Boolean syntax is specific to the bulk endpoint.
        terms = _unique_terms(_selected_groups(view), per_group=3, total=10)
        if not terms:
            raise ValueError("Semantic Scholar query view did not contain compilable terms")
        query = " ".join(terms)
        query = re.sub(r"(?<=\w)[\-\u2010-\u2015](?=\w)", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)


class PubMedQueryCompiler:
    SOURCE = "pubmed"
    FIELD_MAP = {"all": "Title/Abstract", "title": "Title", "abstract": "Title/Abstract"}

    def compile(self, view: QueryView) -> CompiledQuery:
        clauses = [self._compile_group(group) for group in _selected_groups(view)]
        clauses = [clause for clause in clauses if clause]
        if not clauses:
            raise ValueError("PubMed query view did not contain compilable terms")
        query = " AND ".join(clauses)
        exclusions = [self._compile_term(value, "Title/Abstract") for value in view.exclusions]
        exclusions = [value for value in exclusions if value]
        if exclusions:
            exclusion_clause = exclusions[0] if len(exclusions) == 1 else f"({' OR '.join(exclusions)})"
            query += f" NOT {exclusion_clause}"
        validation = validate_source_query(self.SOURCE, query)
        if not validation.ok:
            raise ValueError(validation.issue)
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    def _compile_group(self, group: ConceptGroup) -> str:
        field = self.FIELD_MAP.get(group.field_hint, "Title/Abstract")
        terms = [self._compile_term(value, field) for value in group.terms]
        terms = [value for value in terms if value]
        if not terms:
            return ""
        return terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})"

    @staticmethod
    def _compile_term(value: str, field: str) -> str:
        term = _quoted_term(value)
        return f"{term}[{field}]" if term else ""


class GoogleScholarQueryCompiler:
    SOURCE = "googlescholar"

    def compile(self, view: QueryView) -> CompiledQuery:
        clauses = [self._compile_group(group) for group in _selected_groups(view)]
        clauses = [clause for clause in clauses if clause]
        if not clauses:
            raise ValueError("Google Scholar query view did not contain compilable terms")
        query = " ".join(clauses)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                query += f" -{term}"
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    @staticmethod
    def _compile_group(group: ConceptGroup) -> str:
        terms = [_quoted_term(value) for value in group.terms]
        terms = [value for value in terms if value]
        if not terms:
            return ""
        return terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})"


class PaperHubQueryCompiler:
    SOURCE = "paperhub"

    def compile(self, view: QueryView) -> CompiledQuery:
        clauses = [self._compile_group(group) for group in _selected_groups(view)]
        clauses = [clause for clause in clauses if clause]
        if not clauses:
            raise ValueError("PaperHub query view did not contain compilable terms")
        query = " ".join(clauses)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                query += f" -{term}"
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    @staticmethod
    def _compile_group(group: ConceptGroup) -> str:
        terms = [_quoted_term(value) for value in group.terms]
        terms = [value for value in terms if value]
        return " OR ".join(terms)


class WosQueryCompiler:
    SOURCE = "wos"

    def compile(self, view: QueryView) -> CompiledQuery:
        groups = [self._compile_group(group) for group in _selected_groups(view)]
        groups = [group for group in groups if group]
        if not groups:
            raise ValueError("Web of Science query view did not contain compilable terms")
        topic = " AND ".join(groups)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                topic += f" NOT {term}"
        query = f"TS=({topic})"
        validation = validate_source_query(self.SOURCE, query)
        if not validation.ok:
            raise ValueError(validation.issue)
        return CompiledQuery(source=self.SOURCE, view_id=view.view_id, query=query, purpose=view.purpose)

    @staticmethod
    def _compile_group(group: ConceptGroup) -> str:
        terms = [_quoted_term(value) for value in group.terms]
        terms = [value for value in terms if value]
        if not terms:
            return ""
        return terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})"


_QUERY_COMPILERS: dict[str, QueryCompiler] = {
    "arxiv": ArxivQueryCompiler(),
    "crossref": CrossrefQueryCompiler(),
    "googlescholar": GoogleScholarQueryCompiler(),
    "openalex": OpenAlexQueryCompiler(),
    "paperhub": PaperHubQueryCompiler(),
    "pubmed": PubMedQueryCompiler(),
    "semanticscholar": SemanticScholarQueryCompiler(),
    "wos": WosQueryCompiler(),
}


def supports_query_portfolio(source: str) -> bool:
    return str(source or "").strip().lower() in _QUERY_COMPILERS


def query_compiler_sources() -> tuple[str, ...]:
    return tuple(sorted(_QUERY_COMPILERS))


def compile_query_view(source: str, view: QueryView) -> CompiledQuery:
    source_id = str(source or "").strip().lower()
    compiler = _QUERY_COMPILERS.get(source_id)
    if compiler is None:
        raise ValueError(f"No structured query compiler is available for source={source_id}")
    return compiler.compile(view)
