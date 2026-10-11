# Security Policy

## Supported Versions

PaperSeek is currently in beta. Security fixes target the latest `main` branch and the latest published package version, if any.

## Reporting a Vulnerability

Please report security issues privately to:

```text
support@paperseek.app
```

Do not open a public issue for leaked credentials, account access problems, or vulnerabilities involving API keys.

## Secrets Handling

- Unsaved Web form inputs live in browser memory and are lost on reload. Testing a connection sends those inputs to the server; it does not save a connection.
- Saving a model connection or data-source key persists it in the Community database. Secret values are encrypted with AES-GCM using `credentials.master.key` beside the database; connection metadata is also stored. Saved secrets survive page reloads and server restarts. Settings responses expose only key status and a masked suffix, not the saved plaintext key.
- Submitted tasks may receive a separate encrypted credential copy for execution and recovery, including credentials submitted directly through the API. These per-run copies expire after 25 hours; clearing saved connections does not revoke credentials already copied to submitted tasks.
- PaperSeek does not store API keys in browser `localStorage` or `sessionStorage`. Browser storage keeps preferences such as language and sidebar visibility; result caches and unsaved drafts are in memory. Clearing browser storage does not delete server-side saved secrets.
- Manage saved connections and source keys in Settings, or use **Settings → User → Clear saved keys** to remove them together. Back up and protect the database, artifacts, and credential master key as one data directory.
- CLI and MCP provider credentials come from process environment variables. Deployment `.env` files contain plaintext values and must be protected separately.
- Do not commit `.env` files containing real credentials, local databases, credential master keys, build output, or caches.
- Agent Skill files must not contain real API keys.

PaperSeek does not bypass paywalls, download protected PDFs, or manage publisher/database login sessions.
