# Use your own keys

Run tasks with your own model and data-source keys instead of PaperSeek Service. Tasks with your own keys use no credits; provider charges and rate limits belong to your own provider accounts.

## Set up your keys

1. Select **Your own key** from the account menu at the bottom of the sidebar.
2. In **Settings › Model service**, choose **Add connection**, fill in the model details and key, then click **Save** (see [Models & ranking](../guide/models.md)).
3. In **Settings › Data sources**, choose **Configure** (or **Configure key**) for a source and save its key. With your own key, every source that takes a key requires one, including OpenAlex, PubMed, and Semantic Scholar; arXiv, Crossref, and PaperHub work without one.

Model keys and data-source keys are separate. A model API key does not grant access to a literature database.

## Public endpoints only

Online, only public model endpoints are accepted. Localhost, `127.0.0.1`, private network addresses, and other non-public destinations are blocked. To use a model on your own machine or network, run the [Community edition](../self-hosting/index.md).

## Related

- [Data & privacy](privacy.md) — how saved keys are stored and who can see them.
- [Service & credits](credits.md) — the alternative: PaperSeek-provided models.
