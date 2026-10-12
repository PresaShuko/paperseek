"""Sparse keyword co-occurrence and bibliographic coupling with bounded work."""

from collections import Counter, defaultdict
from itertools import combinations
from math import sqrt

from paperseek_core.bibliometrics.models import (
    MetricCorpus,
    MetricNetwork,
    NetworkEdge,
    NetworkNode,
    NetworkRequest,
    NetworkTooDense,
)

MAX_PAIR_CONTRIBUTIONS = 1_000_000
MAX_UNIQUE_PAIRS = 300_000


def network(corpus: MetricCorpus, request: NetworkRequest) -> MetricNetwork:
    pairs: Counter[tuple[str, str]] = Counter()
    excluded = 0
    if request.kind == "keywords":
        eligible = [paper for paper in corpus.papers if paper.keywords]
        counts = Counter(term for paper in eligible for term in set(paper.keywords))
        nodes = {
            term: NetworkNode(id=term, label=term, count=count)
            for term, count in counts.items()
            if count >= request.min_occurrences
        }
        groups = (sorted(set(paper.keywords) & nodes.keys()) for paper in eligible)
    else:
        eligible = [paper for paper in corpus.papers if paper.references]
        postings: dict[str, list[str]] = defaultdict(list)
        for paper in eligible:
            for ref in set(paper.references):
                postings[ref].append(paper.id)
        retained = {
            ref: ids
            for ref, ids in postings.items()
            if request.max_reference_frequency is None
            or len(ids) <= request.max_reference_frequency
        }
        excluded = len(postings) - len(retained)
        counts = Counter(identity for ids in retained.values() for identity in ids)
        nodes = {
            paper.id: NetworkNode(
                id=paper.id, label=paper.title, count=counts[paper.id], year=paper.year
            )
            for paper in eligible
            if counts[paper.id] >= request.min_occurrences
        }
        groups = (sorted(set(ids) & nodes.keys()) for ids in retained.values())
    work = 0
    for group in groups:
        work += len(group) * (len(group) - 1) // 2
        if work > MAX_PAIR_CONTRIBUTIONS:
            raise NetworkTooDense("network_too_dense")
        for pair in combinations(group, 2):
            if pair not in pairs and len(pairs) >= MAX_UNIQUE_PAIRS:
                raise NetworkTooDense("network_too_dense")
            pairs[pair] += 1
    edges = [
        NetworkEdge(
            source=a,
            target=b,
            weight=count,
            similarity=round(count / sqrt(nodes[a].count * nodes[b].count), 6),
        )
        for (a, b), count in pairs.items()
        if count >= request.min_weight
    ]
    edges.sort(
        key=lambda edge: (-edge.weight, -edge.similarity, edge.source, edge.target)
    )
    strengths = Counter()
    for edge in edges:
        strengths[edge.source] += edge.weight
        strengths[edge.target] += edge.weight
    selected = sorted(nodes, key=lambda key: (-strengths[key], -nodes[key].count, key))[
        : request.max_nodes
    ]
    selected_set = set(selected)
    shown = [
        edge
        for edge in edges
        if edge.source in selected_set and edge.target in selected_set
    ][: request.max_edges]
    # Connected components, explicitly not an inferred semantic topic model.
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in shown:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    components: dict[str, int] = {}
    for key in selected:
        if key in components:
            continue
        group, pending = len(set(components.values())) + 1, [key]
        while pending:
            current = pending.pop()
            if current in components:
                continue
            components[current] = group
            pending.extend(adjacency[current] - components.keys())
    warnings = []
    if len(selected) < len(nodes) or len(shown) < len(edges):
        warnings.append("network_display_limited")
    if excluded:
        warnings.append("frequent_references_excluded")
    return MetricNetwork(
        parameters=request,
        corpus_count=len(corpus.papers),
        eligible_paper_count=len(eligible),
        eligible_node_count=len(nodes),
        total_edge_count=len(edges),
        excluded_reference_count=excluded,
        nodes=[
            nodes[key].model_copy(update={"group": components[key]}) for key in selected
        ],
        edges=shown,
        warnings=warnings,
    )
