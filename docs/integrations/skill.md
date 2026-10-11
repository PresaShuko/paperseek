# Agent Skill

Use PaperSeek from an agent that supports Skills and can run local commands. The Skill guides the agent through installation checks, configuration, literature searches, and reading saved results.

Searches run in your local Community installation. History and artifacts stay in its local storage; model and source requests use the services you configure. No PaperSeek account is required.

## Add the Skill

The Skill lives at [integrations/skills/paperseek](https://github.com/paperseek/paperseek/tree/main/integrations/skills/paperseek) in the repository.

1. Use your agent's Skill installer to add that directory, or copy the complete `paperseek` folder into the project or user Skill directory documented by your client.
2. Keep `SKILL.md` and the `references/` directory together. The references contain installation steps and the supported command and source options.
3. Reload the client's Skills if required, then check that it recognizes the name **paperseek**.

You can add the Skill before installing Community. Copying the Skill itself does not install Python, PaperSeek, or model credentials.

## First use

Ask your agent to use PaperSeek for a concrete research question:

> Use the PaperSeek Skill to find literature on how open-source funding affects software maintenance. Check the local installation first; if PaperSeek is missing, install it in an isolated environment and check the configuration. Search OpenAlex, save the run, and summarize relevant papers with source links.

The Skill guides the agent to:

1. **Check the installation.** Locate `paperseek`, inspect its version, and reuse an existing environment or executable path.
2. **Install if needed.** Use Python 3.12+ and an isolated environment. An agent with execution permissions can perform the installation; otherwise it provides the steps for you.
3. **Check configuration.** Run `paperseek doctor --json` without a live search. Resolve missing required model or source settings first.
4. **Search locally.** Select the source, submit the question through the Community CLI, and retain the run ID, status, warnings, and results.

An existing installation is not automatically upgraded, and its data is not automatically migrated. For a version change, follow the [upgrade guide](../self-hosting/upgrade.md).

## Configure models and sources

Provide your model connection and source credentials through the local process environment or your agent client's private environment settings. The Skill uses the same `PAPERSEEK_*` settings as Community. See [configuration](../reference/configuration.md), [models](../guide/models.md), and [data sources](../guide/sources.md).

Do not put real keys in a conversation, `SKILL.md`, or committed client settings. If a required value is missing, the agent should report its name and guide you to configure it locally.

The CLI reads its process environment. Values entered only in the Web form do not automatically configure a separate agent process, and an `.env` file is not loaded automatically by the CLI.

## Continue a research task

You can ask the agent to inspect a saved run, summarize warnings, retrieve normalized paper metadata, or help export results. For interactive filtering, history, and citation maps, open the local Web workspace using the same database.

For example:

> Open the saved PaperSeek run we just created. Show its status and source, summarize the most relevant papers, and help me export the results as CSV.

PaperSeek relevance scores help screen literature; check the original studies before relying on a generated synthesis. This Skill does not automatically read paper PDFs or perform a complete systematic review.

## Skill, MCP, or HTTP API?

| Entry point | Use it when |
| --- | --- |
| **Agent Skill** | Your agent can run local commands and needs guidance on installing and using PaperSeek |
| [MCP](mcp.md) | Your assistant uses structured tools for starting, inspecting, cancelling, and exporting searches |
| [HTTP API](api.md) | You are building an application against the running PaperSeek server |

The Skill works through the CLI without installing MCP or starting a Web server. It can also guide an agent to use an existing local API or matched MCP integration when appropriate. See the [CLI guide](cli.md) for the underlying commands.
