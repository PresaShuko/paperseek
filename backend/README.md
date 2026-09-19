# PaperSeek backend

This directory is the Python 3.12 backend boundary for PaperSeek v0.3.0.

## Optional abstract enrichment

Search keeps provider abstracts without making extra Crossref abstract requests by
default. Use `paperseek search "your question" --fetch-abstracts`, or set
`fetch_abstracts: true` in a run submission or MCP `start_search`, to fill missing
abstracts for papers with a DOI. The choice is saved with the run for recovery;
an unavailable abstract only adds a warning. This is separate from the optional
Crossref candidate citation-count/year enrichment.

## Shared Web source delivery

The Community wheel includes `paperseek_community/web_source.zip`, built from
the same checkout as the backend. It contains the canonical Vue source, public
assets and npm manifests, not node_modules, test output or environment files.
Hosted verifies its existing Community wheel lock before extracting these build
inputs; it does not maintain a second copy of the search/results UI. The installed
Community server still serves only the prebuilt `static/` assets and needs no Node.
