"""Freeze native abstracts and validate every quote against its source text."""
from __future__ import annotations

import hashlib
from difflib import SequenceMatcher, get_close_matches
from html import unescape
from html.parser import HTMLParser
import json
import re
import unicodedata

from paperseek_core.models import FinalPaperResult
from paperseek_core.review.models import (
    EvidenceBatch, EvidenceCard, ReviewEvidence, ReviewOutline, ReviewPaper, SectionBody,
)


PROMPT_VERSION = "abstract-review.v3"
PAPER_MENTION = re.compile(r"(?<![A-Za-z0-9_])p_\d+(?![A-Za-z0-9_])")
_MISSING = {"", "n/a", "na", "none", "null", "no abstract", "no abstract available",
            "abstract not available", "how to cite", "暂无摘要", "无摘要", "摘要缺失"}
_QUOTE_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
# Words for loose quote matching: each CJK character, or a run of letters and digits
# that keeps decimals together (0.05). Case, punctuation, hyphens and spacing are ignored.
_WORD = re.compile(r"[㐀-鿿豈-﫿]|[^\W_]+(?:[.,]\d+)*")
_FUZZY_MATCH = 0.8
_SHORT_QUOTE = 4


class _AbstractText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")


def normalize_abstract(value: str) -> str:
    parser = _AbstractText()
    parser.feed(value)
    text = " ".join(re.sub(r"\\r\\n|\\[rn]", " ", unescape("".join(parser.parts))).split())
    if re.fullmatch(r"This thesis was submitted for the award of [^.?!]+ and was awarded by [^.?!]+\.?", text, re.I):
        return ""
    return "" if text.casefold().strip(" .。:：") in _MISSING else text


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def snapshot(record: FinalPaperResult, run_id: str, rank: int) -> ReviewPaper:
    abstract = normalize_abstract(record.abstract)
    return ReviewPaper(
        id=f"p_{rank:03}", source_run_id=run_id, source_uid=record.uid,
        title=record.title, authors=record.authors, year=record.year or record.publish_year,
        venue=record.venue, doi=record.doi, url=record.url, provider=record.provider or record.source,
        source_rank=rank, original_abstract=record.abstract, abstract=abstract,
        abstract_hash=hashlib.sha256(abstract.encode()).hexdigest(), has_abstract=bool(abstract),
    )


def _words(text: str) -> list[tuple[str, int, int]]:
    return [(unicodedata.normalize("NFKC", m.group()).casefold(), m.start(), m.end()) for m in _WORD.finditer(text)]


def locate_quote(quote: str, abstract: str) -> tuple[int, int] | None:
    """Find the abstract span a quote was taken from, tolerating small copying slips.

    The prompt still asks for exact spans; small models change case, hyphenation,
    spacing or punctuation (p<0.05 for p < 0.05), so this compares words and accepts
    a span that is at least 80% similar. Quotes under four words must match exactly.
    """
    source, wanted = _words(abstract), [word for word, _, _ in _words(quote)]
    if not source or not wanted:
        return None
    words = [word for word, _, _ in source]
    anchor = SequenceMatcher(None, words, wanted, autojunk=False).find_longest_match(0, len(words), 0, len(wanted))
    if anchor.size == 0:
        return None
    slack, best = max(2, len(wanted) // 4), (0.0, 0, 0)
    first = anchor.a - anchor.b
    for start in range(max(0, first - slack), min(len(words) - 1, first + slack) + 1):
        for length in range(max(1, len(wanted) - slack), len(wanted) + slack + 1):
            if start + length > len(words):
                break
            ratio = SequenceMatcher(None, words[start:start + length], wanted, autojunk=False).ratio()
            if ratio > best[0]:
                best = (ratio, start, length)
    ratio, start, length = best
    if ratio < (1.0 if len(wanted) < _SHORT_QUOTE else _FUZZY_MATCH):
        return None
    return source[start][1], source[start + length - 1][2]


_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|…|\[\.\.\.\])\s*")


def _locate(quote: str, source: str, abstract: str) -> tuple[int, int] | None:
    # Match formatting whitespace in old snapshots too, retaining original offsets and text.
    words = re.split(r"(?:\s|\\r\\n|\\[rn])+", quote.strip().translate(_QUOTE_TYPOGRAPHY))
    match = re.search(r"(?:\s|\\r\\n|\\[rn])+".join(re.escape(word) for word in words), source)
    return (match.start(), match.end()) if match else locate_quote(quote, abstract)


def validate_cards(batch: EvidenceBatch, papers: list[ReviewPaper], signature: str,
                   dropped: list[str] | None = None) -> list[EvidenceCard]:
    """Keep every quote found in its abstract; a paper fails only when none of its quotes are.

    Quotes joined with an ellipsis are split into their separate spans. Unverifiable quotes are
    dropped (and listed in ``dropped``) while the paper keeps at least one verified quote.
    """
    by_id = {paper.id: paper for paper in papers if paper.has_abstract}
    if {card.paper_id for card in batch.cards} != set(by_id) or len(batch.cards) != len(by_id):
        raise ValueError("Return exactly one evidence card for each supplied paper.")
    result = []
    quote_errors = []
    for draft in batch.cards:
        paper = by_id[draft.paper_id]
        # One-to-one substitutions preserve offsets; stored evidence always uses the original source.
        source = paper.abstract.translate(_QUOTE_TYPOGRAPHY)
        evidence, rejected = [], []
        for item in draft.evidence:
            parts = [part for part in _ELLIPSIS.split(item.quote.strip()) if part.strip()] or [item.quote]
            spans = [_locate(part, source, paper.abstract) for part in parts]
            if not all(spans):
                rejected.append(f"{paper.id}: {item.quote[:180]!r}")
                continue
            for start, end in spans:
                # Evidence always keeps the abstract's own text, never the model's copy.
                quote = paper.abstract[start:end]
                key = "e_" + fingerprint([paper.id, paper.abstract_hash, quote])[:24]
                if any(existing.id == key for existing in evidence):
                    continue
                evidence.append(ReviewEvidence(
                    **item.model_dump(exclude={"quote"}), quote=quote, id=key,
                    paper_id=paper.id, start=start, end=start + len(quote), abstract_hash=paper.abstract_hash,
                ))
        if rejected and not evidence:
            quote_errors.extend(rejected)
            continue
        if dropped is not None:
            dropped.extend(rejected)
        result.append(EvidenceCard(paper_id=paper.id, signature=signature, evidence=evidence[:6]))
    if quote_errors:
        raise ValueError("Non-verbatim quotes: " + "; ".join(quote_errors[:8])
                         + ". Copy exact continuous spans from the original abstracts; preserve capitalization, "
                         "punctuation and sentence order. Do not join, reorder or paraphrase source sentences.")
    return result


def usable_cards(cards: list[EvidenceCard], papers: list[ReviewPaper]) -> list[EvidenceCard]:
    abstracts = {paper.id for paper in papers if normalize_abstract(paper.abstract)}
    return [card for card in cards if card.paper_id in abstracts
            and any(item.category != "scope" for item in card.evidence)]


def validate_outline(outline: ReviewOutline, cards: list[EvidenceCard], *, require_all: bool = True) -> ReviewOutline:
    available = {card.paper_id for card in cards if card.evidence}
    assigned = set()
    for section in outline.sections:
        if unknown := set(section.paper_ids) - available:
            raise ValueError(f"Section {section.id} references papers without valid evidence: {sorted(unknown)}. "
                             f"Use these supplied paper IDs: {sorted(available)}.")
        assigned.update(section.paper_ids)
    if require_all and assigned != available:
        raise ValueError(f"The outline is missing these supplied papers: {sorted(available - assigned)}. "
                         "Place each in a relevant section and its paragraph plan, without adding sections.")
    return outline


def evidence_index(cards: list[EvidenceCard]) -> dict[str, ReviewEvidence]:
    return {evidence.id: evidence for card in cards for evidence in card.evidence}


def validate_body(body: SectionBody, cards: list[EvidenceCard], paper_ids: list[str]) -> SectionBody:
    evidence = evidence_index(cards)
    allowed = {key for key, item in evidence.items() if item.paper_id in paper_ids}
    for paragraph in body.paragraphs:
        if invalid := set(paragraph.evidence_ids) - allowed:
            suggestions = {key: get_close_matches(key, sorted(allowed), n=3, cutoff=0.3)
                           for key in sorted(invalid)}
            raise ValueError("Invalid evidence IDs: " + repr(suggestions)
                             + ". Values list similar allowed IDs; select the actual supporting evidence "
                             "from the input and copy its complete ID exactly.")
        if re.search(r"\[\d+(?:\s*[,–-]\s*\d+)*\]", paragraph.text):
            raise ValueError("Return evidence IDs separately; do not invent numbered citations.")
    return body


# Eight or more English words in a row, outside parentheses, is an English sentence or title.
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'’-]*(?:[\s,;:/&-]+[A-Za-z][A-Za-z'’-]*){7,}")
_PARENTHETICAL = re.compile(r"[（(][^（）()]*[)）]")


class CitationStyleError(ValueError):
    """The paragraphs are grounded but miss a writing rule; the draft is usable if repair fails."""

    def __init__(self, issues: list[tuple[int, str, str]]) -> None:
        super().__init__("\n".join(message for _, _, message in issues))
        self.issues = issues


def citation_style_issues(body: SectionBody, cards: list[EvidenceCard], language: str = "en",
                          exempt: frozenset[str] | set[str] = frozenset()) -> list[tuple[int, str, str]]:
    """Inline placement and output language, for paragraphs not already accepted as they are."""
    index = evidence_index(cards)
    issues = []
    for i, paragraph in enumerate(body.paragraphs):
        if paragraph.text in exempt:
            continue
        number = i + 1
        cited = {index[key].paper_id for key in paragraph.evidence_ids if key in index}
        mentions = [(match.start(), match.group()) for match in PAPER_MENTION.finditer(paragraph.text)]
        if unplaced := cited - {paper_id for _, paper_id in mentions}:
            issues.append((i, "unplaced", f"Paragraph {number} cites {sorted(unplaced)} without naming them in the text. Put each "
                              "cited paper's ID right after the claim it supports, e.g. '... (p_003).'"))
        else:
            # A paragraph whose sources all trail its last sentence reads like a citation dump.
            text = paragraph.text.rstrip()
            final_sentence = max(text.rfind(mark, 0, max(len(text) - 1, 0)) for mark in ".。!?！？;；")
            if len(cited) >= 3 and final_sentence > 0 and all(position > final_sentence for position, _ in mentions):
                issues.append((i, "grouped", f"Paragraph {number} groups all its citations at the end. Attach each paper ID to "
                                  "the specific claim it supports within the paragraph."))
        if language == "zh" and _LATIN_RUN.search(_PARENTHETICAL.sub(" ", PAPER_MENTION.sub(" ", paragraph.text))):
            issues.append((i, "language", f"Paragraph {number} contains English sentences or titles. Write it entirely in "
                              "Chinese: refer to studies by their paper IDs and translate their findings."))
    return issues


def validate_mentions(body: SectionBody, cards: list[EvidenceCard], *, language: str = "en",
                      exempt: frozenset[str] | set[str] = frozenset()) -> None:
    """Citations sit beside the claims they support, so a reader can tell which study says what."""
    index = evidence_index(cards)
    for paragraph in body.paragraphs:
        cited = {index[key].paper_id for key in paragraph.evidence_ids}
        if missing := {match.group() for match in PAPER_MENTION.finditer(paragraph.text)} - cited:
            raise ValueError(f"Text mentions {sorted(missing)} without evidence from those papers in this paragraph. "
                             "Correct the attribution or include the actual supporting evidence IDs.")
    if issues := citation_style_issues(body, cards, language, exempt):
        raise CitationStyleError(issues)
