"""Bounded cross-section editorial checks; never overwrite a user's prose."""
from __future__ import annotations

from paperseek_core.ports import CancellationToken, LLMPort
from paperseek_core.review.models import (
    ConsistencyCheck,
    ConsistencyFinding,
    ReviewOutline,
    WrittenSection,
)
from paperseek_core.review.structured import (
    structured_call,
)


async def check_consistency(llm: LLMPort, cancellation: CancellationToken,
                            outline: ReviewOutline, bodies: list[WrittenSection]) -> list[ConsistencyFinding]:
    by_id = {body.section_id: body for body in bodies}
    present = [section for section in outline.sections if section.id in by_id]
    findings = []
    # Overlapping neighbours preserve full text and bound the input by two sections.
    for left, right in zip(present, present[1:], strict=False):
        ids = {left.id, right.id}

        def validate(result: ConsistencyCheck) -> None:
            if any(not set(item.section_ids) <= ids for item in result.findings):
                raise ValueError("Only reference the supplied section IDs.")

        result = await structured_call(
            llm, cancellation, "consistency_check",
            'Return {"has_material_issue":false,"findings":[]} when there are no material issues. '
            'Otherwise return {"has_material_issue":true,"findings":[{"section_ids":["s1","s2"],"reason":"..."}]}. '
            'Findings contain only actionable problems, never confirmations that the text is consistent. '
            'Compare the two sections for '
            'contradictory claims, inconsistent terminology or substantial unnecessary repetition. '
            'For a contradiction, identify two explicit mutually incompatible statements about the same '
            'method, outcome and conditions. Do not infer unstated premises or turn a missing explanation '
            'into a contradiction. Different studies, datasets, objectives or levels of detail can yield '
            'different results. A later refinement can extend a successful approach without contradicting '
            'its earlier reported performance. Treat these as complementary unless the text explicitly '
            'makes incompatible claims. Do not request generic caveats, weaknesses or limitations. '
            'A conclusion may briefly summarize preceding findings. Describe issues in the text language, '
            'at most 500 characters per reason, identifying the conflicting claims or unnecessary repetition.',
            {"sections": [{"id": s.id, "title": s.title, "paragraphs":
                           [p.text for p in by_id[s.id].body.paragraphs]} for s in (left, right)]},
            ConsistencyCheck, max_tokens=1800, validate=validate,
        )
        findings.extend(result.findings)
    return findings
