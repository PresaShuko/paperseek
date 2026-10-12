"""Paper-level full counting, with missing data kept distinct from zero."""

from collections import Counter

from paperseek_core.bibliometrics.models import (
    Coverage,
    MetricBucket,
    MetricCorpus,
    MetricOverview,
)


def overview(corpus: MetricCorpus) -> MetricOverview:
    papers = corpus.papers
    category_totals = {}

    def buckets(field: str, *, many: bool = False, chronological: bool = False):
        counts = Counter()
        for paper in papers:
            value = getattr(paper, field)
            counts.update(
                set(value)
                if many
                else [str(value)]
                if value is not None and value != ""
                else []
            )
        ordered = sorted(
            counts.items(),
            key=lambda item: item[0] if chronological else (-item[1], item[0]),
        )
        category_totals[field] = len(ordered)
        return [
            MetricBucket(label=label, count=count)
            for label, count in (ordered if chronological else ordered[:100])
        ]

    fields = (
        "year",
        "venue",
        "authors",
        "institutions",
        "countries",
        "keywords",
        "references",
        "citations",
        "doi",
    )
    coverage = [
        Coverage(
            field=field,
            total=len(papers),
            available=sum(
                getattr(paper, field) is not None
                if field == "citations"
                else bool(getattr(paper, field))
                for paper in papers
            ),
        )
        for field in fields
    ]
    coverage.append(
        Coverage(
            field="references_available",
            total=len(papers),
            available=sum(paper.references_available for paper in papers),
        )
    )
    return MetricOverview(
        paper_count=len(papers),
        scored_count=sum(paper.scored for paper in papers),
        cited_paper_count=sum((paper.citations or 0) > 0 for paper in papers),
        citation_sum=sum(paper.citations or 0 for paper in papers),
        years=buckets("year", chronological=True),
        venues=buckets("venue"),
        providers=buckets("provider"),
        document_types=buckets("document_types", many=True),
        authors=buckets("authors", many=True),
        institutions=buckets("institutions", many=True),
        countries=buckets("countries", many=True),
        keywords=buckets("keywords", many=True),
        keyword_sources=buckets("keyword_source"),
        citation_sources=buckets("citation_source"),
        coverage=coverage,
        category_totals=category_totals,
    )
