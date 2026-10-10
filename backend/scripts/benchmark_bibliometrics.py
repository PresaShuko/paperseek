"""Opt-in synthetic 3k/10k resource check. No provider, model or production calls.

Run: python scripts/benchmark_bibliometrics.py --output /path/to/report.json
Times are local CPU/filesystem measurements, not Hosted end-to-end latency.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import platform
import tempfile
from time import perf_counter
import tracemalloc
from uuid import uuid4

from paperseek_app.bibliometrics.models import AnalysisRecord
from paperseek_app.bibliometrics.services import AnalysisService
from paperseek_core.bibliometrics.models import (
    MetricCorpus,
    MetricPaper,
    NetworkRequest,
    NetworkTooDense,
)
from paperseek_core.bibliometrics.networks import network
from paperseek_core.bibliometrics.statistics import overview
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.persistence import migrate_database
from paperseek_community.persistence.sqlite_bibliometrics import SQLiteAnalysisStore


def corpus(size: int) -> MetricCorpus:
    return MetricCorpus(
        papers=[
            MetricPaper(
                id=f"paper:{i}",
                title=f"Synthetic literature benchmark {i}",
                doi=f"10.9999/fixture.{i}",
                year=2000 + i % 26,
                venue=f"Journal {i % 200}",
                authors=[f"Author {i % 1000}", f"Author {(i + 1) % 1000}"],
                provider="fixture",
                keywords=[f"topic {(i + j) % 500}" for j in range(5)],
                references=[f"reference:{i // 10}:{j}" for j in range(20)],
                references_available=True,
                institutions=[f"Institute {i % 100}"],
                countries=["SG"],
                citations=i % 100,
                scored=i < 100,
            )
            for i in range(size)
        ],
        scoring_limit=100,
        warnings=["synthetic_fixture"],
    )


def measure(function):
    tracemalloc.start()
    started = perf_counter()
    result = function()
    elapsed = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, {
        "seconds_with_tracemalloc": round(elapsed, 4),
        "python_peak_allocated_mib": round(peak / 1024**2, 2),
    }


def benchmark(size: int):
    data, creation = measure(lambda: corpus(size))
    stats, statistics = measure(lambda: overview(data))
    keywords, keyword_cost = measure(
        lambda: network(data, NetworkRequest(kind="keywords"))
    )
    coupling, coupling_cost = measure(
        lambda: network(data, NetworkRequest(kind="coupling"))
    )
    payload = data.model_dump_json().encode()
    with tempfile.TemporaryDirectory(
        prefix="paperseek-metrics-benchmark-"
    ) as directory:
        root = Path(directory)
        migrate_database(root / "paperseek.db")
        store = SQLiteAnalysisStore(root / "paperseek.db")
        try:
            service = AnalysisService(store, FileArtifactStore(root))
            identity = str(uuid4())
            store.create_analysis(
                AnalysisRecord(
                    id=identity,
                    source_run_id="fixture",
                    title="Benchmark",
                    paper_count=size,
                    scope=data.scope,
                    created_at=datetime.now(timezone.utc),
                    request_digest="fixture",
                    corpus=service._put(identity, "corpus", payload.decode()),
                    overview=service._put(
                        identity, "overview", stats.model_dump_json()
                    ),
                ),
                identity,
            )
            _, first = measure(
                lambda: service.network(identity, NetworkRequest(kind="coupling"))
            )
            _, cached = measure(
                lambda: service.network(identity, NetworkRequest(kind="coupling"))
            )
            detail, detail_cost = measure(lambda: service.get(identity))
            _, history = measure(lambda: store.list_analyses("", 0, 25))
        finally:
            store.close()
    return {
        "papers": size,
        "construct_input": creation,
        "overview": statistics,
        "keyword_network": keyword_cost,
        "coupling_network": coupling_cost,
        "first_network_with_disk": first,
        "cached_network": cached,
        "open_analysis": detail_cost,
        "history": history,
        "corpus_json_bytes": len(payload),
        "corpus_gzip_bytes": len(gzip.compress(payload)),
        "overview_response_bytes": len(detail.model_dump_json().encode()),
        "keyword_response_bytes": len(keywords.model_dump_json().encode()),
        "coupling_response_bytes": len(coupling.model_dump_json().encode()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [benchmark(size) for size in (3000, 10000)]
    dense = MetricCorpus(
        papers=[
            MetricPaper(id=str(i), title=str(i), references=["universal"])
            for i in range(10000)
        ]
    )

    def reject_dense():
        try:
            network(dense, NetworkRequest(kind="coupling", min_occurrences=1))
        except NetworkTooDense:
            return True
        raise AssertionError("Dense input must stop before quadratic allocation")

    rejected, guard_cost = measure(reject_dense)
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "scope": "Synthetic metadata; tracemalloc affects elapsed time. No remote API or browser timings.",
        "results": results,
        "dense_guard": {"rejected": rejected, **guard_cost},
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
