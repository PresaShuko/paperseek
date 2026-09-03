from __future__ import annotations

import os


base_url = os.environ.get("PAPERSEEK_CROSSREF_TEST_SERVER", "").rstrip("/")
if base_url:
    from paperseek_core.sources.crossref import CrossrefSource
    from paperseek_core.sources.openalex import OpenAlexSource
    from paperseek_core.sources.wos import WosSource

    OpenAlexSource.BASE_URL = f"{base_url}/openalex/works"
    CrossrefSource.BASE_URL = f"{base_url}/crossref/works"
    WosSource.BASE_URL = f"{base_url}/wos/documents"
