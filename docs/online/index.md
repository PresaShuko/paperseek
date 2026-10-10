# PaperSeek online

[Open PaperSeek](https://paperseek.app/) to search from your browser. The online edition shares the Community search workflow, results, citation map, and experimental review workspace.

## Choose a mode

Use the mode menu in the navigation bar.

| | PaperSeek Service | Bring Your Own Key |
| --- | --- | --- |
| Model access | Operated by the site | Your model API credentials |
| Search configuration | Source, field, budget, model, and ranking method | Community model and search configuration |
| Model connection | Choose a model from a list | Configure provider, protocol, URL, and key |
| Account | Required | Optional for a temporary search |
| Saved history and reviews | Available when signed in | Available when signed in |

The source access requirements and the model credentials are separate. A model API key does not grant access to a literature database.

## Use PaperSeek Service

1. Sign in and select **PaperSeek Service**.
2. Choose a data source and, if needed, a research field.
3. Choose a model and search budget.
4. Describe the question and start the search.

Local fusion is the default preliminary ranking method. You can also choose Embedding + Rerank or System One when offered. The site manages their connections. Writing models are selected from a list as well.

Available models, sources, and allowances are shown in the application. They can change with the site's configuration.

## Use Bring Your Own Key

Select **Bring Your Own Key**, then configure models as described in [Models & ranking](../guide/models.md). The server makes provider requests using the submitted credentials.

Online BYOK accepts public model endpoints. Localhost, `127.0.0.1`, private network addresses, and other non-public destinations are blocked. To use a model on your own machine or LAN, run the [Community edition](../self-hosting/index.md).

An anonymous search has no saved account history. Temporary results can be lost after expiry or a server restart. Sign in **before starting** a search that you want to retain or use for a review; signing in later does not import an anonymous run.

## When your task is queued

The site limits how many tasks execute at the same time. A queued task shows its queue position and waiting state; it starts when capacity becomes available. Closing and reopening a saved task does not create another copy.

You can cancel while waiting. A full queue or an expired wait requires a later retry. Avoid repeatedly submitting the same question while it is already queued or running.

## Allowances and upstream charges

The account view shows service allowances. Service search allowance is counted on successful completion, including completion with warnings; failed and cancelled searches do not count as successful searches. Managed writing has a separate allowance.

BYOK model charges belong to your provider account. Provider credit and rate limits are separate from PaperSeek allowances.

See [Your account](account.md), [Search](../guide/search.md), and [Troubleshooting](../reference/troubleshooting.md).
