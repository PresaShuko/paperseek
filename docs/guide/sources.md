# Data sources

Choose an index that fits your research. Coverage, metadata, access, and filters vary across providers.

## Source directory

| Source | Community / BYOK access | Focus |
| --- | --- | --- |
| [OpenAlex](https://openalex.org/) | Key recommended | Broad discovery and citation expansion |
| [arXiv](https://arxiv.org/) | No key | Scientific preprints |
| [Crossref](https://www.crossref.org/) | No key | DOI and publication metadata |
| [Semantic Scholar](https://www.semanticscholar.org/) | Optional key | Papers and scholarly graph metadata |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | Optional NCBI key | Biomedical and life-science research |
| Google Scholar via [Serper](https://serper.dev/) | Serper key required | Scholar results through the supported API |
| PaperHub top CS conferences | No key | PaperHub's conference collection |
| [Web of Science Starter](https://developer.clarivate.com/apis/wos-starter) | Clarivate key required | Supported WoS collection when enabled |



PaperSeek Service uses operator-configured source access. BYOK retains source configuration; account capabilities and site policy determine access to any server credential. A model key is not a data-source key.

## Obtain credentials

- [OpenAlex API settings](https://openalex.org/settings/api).
- [Semantic Scholar key request](https://www.semanticscholar.org/product/api#api-key-form).
- [NCBI API guidance](https://www.ncbi.nlm.nih.gov/books/NBK25497/).
- [Serper account](https://serper.dev/).
- [WoS Starter application](https://developer.clarivate.com/apis/wos-starter).

Provider subscriptions and rate limits are separate from PaperSeek accounts and allowances.

## Fields and categories

OpenAlex uses supported discipline options; its semantic lane applies supported filtering behavior. arXiv uses categories. WoS categories and the WoS database selector are separate. Other sources use textual field guidance.

Restricting a field can exclude interdisciplinary work. Start without it unless your research design requires the constraint.

## Missing metadata

Records can lack abstracts, years, citation counts, or open PDF links. Missing metadata is not a quality judgment.

Version 1.0.0-beta has no separate cross-source abstract-filling or citation-count enrichment switch. Choose informative abstracts for review writing.

## Multiple keys

OpenAlex and Serper support key pools separated by whitespace, commas, or semicolons. Requests rotate the starting key; authentication failures are handled separately from transient errors.

Rotation does not change provider terms or guarantee remaining credit. See [configuration](../reference/configuration.md).
