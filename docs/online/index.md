# PaperSeek online

[Open PaperSeek](https://paperseek.app/) to search from your browser. The online edition shares the Community search workflow, results, bibliometrics, citation map, and experimental review workspace. PaperSeek online is in public beta.

## Two ways to run a task

Switch at any time from the account menu at the bottom of the sidebar, or in **Settings › Model APIs**.

| | PaperSeek Service | Your own key |
| --- | --- | --- |
| Models | Provided by PaperSeek, chosen from a list | Your saved model connections |
| Keys | None needed | Saved to your account in Settings |
| Credits | Uses daily credits | No credits |
| Account | Required | Required to save history; a signed-out temporary search is possible |

Model keys and data-source keys are separate. A model API key does not grant access to a literature database.

## Use PaperSeek Service

1. Sign in. PaperSeek Service is the default mode.
2. Describe your question, choose a data source and a search budget.
3. Start the search. The form shows how many credits the task uses and how many are left today.

Searching uses **Auto**, a built-in model chosen by PaperSeek. For reviews, choose **Fast** (the default, quicker) or **Deep Research** (more thorough, slower) as the writing model. Preliminary ranking is set in **Settings › Model APIs**. Available sources are shown in the application.

## Credits

During the public beta every account receives **20 free credits a day**. Only PaperSeek Service uses credits:

| Task | Credits |
| --- | --- |
| Search | 1 |
| Bibliometric analysis | 1 |
| Review | 5 for the whole review |

Credits are deducted when a task starts. A review is charged once, by its first writing task; generating the outline again, writing, and rewriting sections of the same review are free. If a task fails or is cancelled, its credits are returned; a task that completes with warnings is not refunded.

Your remaining credits appear in the sidebar and in **Settings › User**, together with the daily refill time. To ask for a larger allowance during the public beta, email [support@paperseek.app](mailto:support@paperseek.app) with your account ID (copy it in Settings › User), your institution, and how you use PaperSeek.

## Use your own key

1. Select **Your own key** from the account menu.
2. In **Settings › Model APIs**, choose **Add connection**, fill in the model details and key, then click **Save** (see [Models & ranking](../guide/models.md)).
3. In **Settings › Data sources**, choose **Configure** (or **Configure key**) for a source and save its key. With your own key, every source that takes a key requires one, including OpenAlex, PubMed, and Semantic Scholar; arXiv, Crossref, and PaperHub work without one.

Keys are encrypted on the PaperSeek server, used only for your own tasks, and never shown again; the page displays only their last four characters. Tasks with your own key use no credits. Provider charges and rate limits belong to your own provider account.

Online, only public model endpoints are accepted. Localhost, `127.0.0.1`, private network addresses, and other non-public destinations are blocked. To use a model on your own machine or network, run the [Community edition](../self-hosting/index.md).

## Search without signing in

Without an account you can run a temporary search: choose a provider and model, and type your model key (and a data-source key if the source needs one) directly into the search form. Keys are used for that search only and are never saved, including in the browser.

A temporary search is held in server memory. You can refresh the tab while it is available, but it is not added to history, and it may be gone after the tab closes, it expires, or the service restarts. Bibliometrics, reviews, history, and Settings require an account. Sign in **before starting** a search you want to keep; signing in later does not import a temporary search.

## When your task is queued

The site limits how many tasks run at the same time. A queued task shows its position and starts automatically when there is room; there is no need to submit it again. You can leave the queue while waiting, which returns any credits.

See [Your account](account.md), [Search](../guide/search.md), and [Troubleshooting](../reference/troubleshooting.md).
