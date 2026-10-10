# Your first search

Run PaperSeek locally, connect a model, and turn a question into a reading list.

Prefer to skip installation? Open [PaperSeek online](https://paperseek.app/) and follow the [online guide](../online/index.md).

## 1. Install

Use **Python 3.12 or newer** and an isolated environment.

::: code-group
~~~bash [macOS / Linux]
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "paperseek==1.0.0b1"
~~~
~~~powershell [Windows PowerShell]
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "paperseek==1.0.0b1"
~~~
:::

For a 1.0.0-beta1 source checkout, use `python -m pip install ./backend` instead. After changing frontend source, follow the [contributor build instructions](../contributing.md).

## 2. Start

~~~bash
paperseek serve
~~~

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. Keep the terminal running while you use the local app.

The package includes the web interface; Node.js is not required to run it.

## 3. Connect a model

Open **Settings → Models and ranking** at the bottom of the sidebar, select a provider and model, then enter your key. For a custom service, check the base URL and protocol as well. Choose **Done** to return to the search draft.

OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages are distinct protocols. A model name alone does not identify the right one.

Use **Check configuration** before the first run. To supply deployment defaults instead, see [configuration](../reference/configuration.md).

## 4. Ask a question

> How does open-source software obtain funding for long-term maintenance?

Choose **OpenAlex**, supply a source key if available, and only restrict the research field when needed. Leave the budget on **Auto** for a first run, or choose a budget to match the breadth of your question.

Select the arrow button, or press **Ctrl+Enter / ⌘+Enter**. Follow the stages while PaperSeek searches and ranks.

## 5. Read the results

Open **Results**, inspect abstracts and relevance explanations, and export CSV or JSON. Community saves history locally.

Use the search history sidebar to reopen a run, **Citation evidence** to explore available citation data, or select papers for an [experimental review](reviews.md). The [Bibliometrics](bibliometrics.md) tab analyzes the full retrieved candidate corpus.

## If something fails

Start with [troubleshooting](../reference/troubleshooting.md). For a local setup check:

~~~bash
paperseek doctor --json
~~~

A valid configuration does not guarantee available credit or uninterrupted upstream service throughout a long search.
