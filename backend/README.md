# PaperSeek backend

This directory is the Python 3.12 backend boundary for PaperSeek v0.3.0.

## Shared Web source delivery

The Community wheel includes `paperseek_community/web_source.zip`, built from
the same checkout as the backend. It contains the canonical Vue source, public
assets and npm manifests, not node_modules, test output or environment files.
Hosted verifies its existing Community wheel lock before extracting these build
inputs; it does not maintain a second copy of the search/results UI. The installed
Community server still serves only the prebuilt `static/` assets and needs no Node.
