"""Freeze native abstracts and validate every quote against its source text."""
from __future__ import annotations

import hashlib
from difflib import get_close_matches
from html import unescape
from html.parser import HTMLParser
import json
import re

from paperseek_core.models import FinalPaperResult
from paperseek_core.review.models import (
    EvidenceBatch, EvidenceCard, ReviewEvidence, ReviewOutline, ReviewPaper, SectionBody,
)


PROMPT_VERSION = "abstract-review.v3"
PAPER_MENTION = re.compile(r"(?<![A-Za-z0-9_])p_\d+(?![A-Za-z0-9_])")
_MISSING = {"", "n/a", "na", "none", "null", "no abstract", "no abstract available",
            "abstract not available", "how to cite", "暂无摘要", "无摘要", "摘要缺失"}
_QUOTE_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


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


def validate_cards(batch: EvidenceBatch, papers: list[ReviewPaper], signature: str) -> list[EvidenceCard]:
    by_id = {paper.id: paper for paper in papers if paper.has_abstract}
    if {card.paper_id for card in batch.cards} != set(by_id) or len(batch.cards) != len(by_id):
        raise ValueError("Return exactly one evidence card for each supplied paper.")
    result = []
    quote_errors = []
    for draft in batch.cards:
        paper = by_id[draft.paper_id]
        # One-to-one substitutions preserve offsets; stored evidence always uses the original source.
        source = paper.abstract.translate(_QUOTE_TYPOGRAPHY)
        evidence = []
        for item in draft.evidence:
            # Match formatting whitespace in old snapshots too, retaining original offsets and text.
            words = re.split(r"(?:\s|\\r\\n|\\[rn])+", item.quote.strip().translate(_QUOTE_TYPOGRAPHY))
            match = re.search(r"(?:\s|\\r\\n|\\[rn])+".join(re.escape(word) for word in words), source)
            if match is None:
                quote_errors.append(f"{paper.id}: {item.quote[:180]!r}")
                continue
            quote, start = paper.abstract[match.start():match.end()], match.start()
            evidence.append(ReviewEvidence(
                **item.model_dump(exclude={"quote"}), quote=quote,
                id="e_" + fingerprint([paper.id, paper.abstract_hash, quote])[:24],
                paper_id=paper.id, start=start, end=start + len(quote), abstract_hash=paper.abstract_hash,
            ))
        result.append(EvidenceCard(paper_id=paper.id, signature=signature, evidence=evidence))
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


def validate_mentions(body: SectionBody, cards: list[EvidenceCard]) -> None:
    index = evidence_index(cards)
    for paragraph in body.paragraphs:
        cited = {index[key].paper_id for key in paragraph.evidence_ids}
        missing = set(PAPER_MENTION.findall(paragraph.text)) - cited
        if missing:
            raise ValueError(f"Text mentions {sorted(missing)} without evidence from those papers in this paragraph. "
                             "Correct the attribution or include the actual supporting evidence IDs.")
