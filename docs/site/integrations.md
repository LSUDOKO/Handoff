# Integrations

Handoff acts through Gmail, Linear, Slack and GitHub. A credential is entered once — in `.env` or on the Credentials page — and every check that says it is connected is a real call, not a test that a variable is set. This page is the setup for each service and how to verify it.

## How credentials work

Every tool reads its key from the environment. The Credentials page stores what you paste and puts it into the process environment; a value already in `.env` or your shell wins over a stored one, so a key set outside the UI is never silently overridden. The browser only ever sees a masked value and a fingerprint.

Work through the services in order and run `handoff doctor` after each. Then, when the ones you use are green:

```bash
USE_MOCK_TOOLS=false
```

Until then the agent runs against a synthetic inbox and mocked actions, which is the right place to learn how it behaves.

## Gmail

The heaviest step, because Google requires a Cloud project — but there is **no key to paste**. The Gmail MCP server does its own OAuth: one browser sign-in, then it holds a refresh token on disk and renews it forever after. A pasted access token would expire within the hour and break the next morning's scheduled run, so Handoff does not ask for one.

Handoff asks for the `gmail.modify` scope — read, archive, label, draft. It cannot send mail, by design.

1. In the Google Cloud console, create a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **OAuth consent screen**: External; add yourself as a test user.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.**
5. Download the client JSON and save it as `~/.gmail-mcp/gcp-oauth.keys.json`.
6. Open **Credentials** in Handoff → **Gmail** → **Sign in with Google**. This opens your browser for the consent screen once. From a terminal the same step is `npx -y @gongrzhe/server-gmail-autoauth-mcp auth`.
7. `handoff doctor gmail` starts the real MCP server and reports how many tools came back live.

The signed-in token lives at `~/.gmail-mcp/credentials.json`. Node.js is required; `doctor` says so if `npx` is missing.

Before the first live run, narrow the query. The template fetches `is:unread newer_than:12h`; against a real mailbox, edit it to `newer_than:1h` first. The gate protects you from *wrong* actions, not from *many* actions. Watch one small batch.

## Linear

The easiest of the four. Handoff talks to Linear's own remote MCP server at `https://mcp.linear.app/mcp`.

1. Linear → **Settings → API → Personal API keys** → create one.
2. `LINEAR_API_KEY=lin_api_...` in `.env`, or paste it on the Credentials page.
3. `handoff doctor linear` prints your name and email.

Linear wants the key raw in the `Authorization` header, with no `Bearer` prefix. A `authentication failed` error almost always means a prefix was added.

## Slack

Either a bot token or an incoming webhook works. Slack has no maintained MCP server, so Handoff talks to the Slack Web API directly.

**Bot token — better.** It reports real delivery failures, and it can post to any channel it has been invited to.

1. <https://api.slack.com/apps> → **Create New App** → From scratch.
2. **OAuth & Permissions** → bot token scopes: `chat:write` (add `channels:read` if a workflow should read channels).
3. **Install to Workspace** and copy the `xoxb-...` token.
4. `SLACK_BOT_TOKEN=xoxb-...`
5. **Invite the bot to the channel**: `/invite @YourApp` in `#daily-triage`. Without this you get `not_in_channel`.
6. `handoff doctor slack` reports the bot and the team it authenticated as.

**Webhook — faster.** **Incoming Webhooks** → activate → **Add New Webhook to Workspace**, then `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`. A webhook is bound to one channel and returns 200 even when nobody sees the message, so `doctor` can only report it as set, not verified.

A completion message with `"notify": "slack"` goes to the workflow's `channel`; a "decision is waiting" notification goes wherever `NOTIFY_CHANNEL=slack` points.

## GitHub

Handoff uses GitHub's official remote MCP server.

1. <https://github.com/settings/tokens> → **Fine-grained tokens**.
2. Grant **Issues: read & write** and **Pull requests: read** on the repositories you care about.
3. `GITHUB_TOKEN=github_pat_...`
4. `handoff doctor github`.

## Web fetch, browser and code

Three more integrations need no account:

- `web` — the reference MCP fetch server, run in-process from your Python environment. Install it with the `web` extra. The competitor-pricing template reads a live page through it, which makes it the one integration a fresh clone can exercise for real.
- `browser` — AgentCore Browser, for pages that need a real renderer. Falls back to a plain HTTP fetch when AgentCore is unavailable.
- `code_interpreter` — AgentCore Code Interpreter, for data processing and report generation.

## Tool servers

The **Tool servers** page is the MCP registry as a catalogue. For each server you can probe it, list its tools with their schemas, **call one live** with arguments you type, and see which workflows use it. Servers from the registry install with one click; your own stdio servers can be added by command and arguments. Connections are opened lazily and reused for the life of the process, so a run that touches Gmail three times starts one subprocess, not three.

## `handoff doctor`

Every check makes a real call and prints one line:

```
Handoff doctor — provider: groq

  PASS  Groq API   qwen/qwen3.8-27b — 7,812/8,000 tokens left this minute
  SKIP  Anthropic  no key set
  PASS  Speech     Polly Matthew (neural) + Transcribe streaming in ap-northeast-2
  PASS  Gmail      signed in — 6 tools live
  FAIL  Slack      not_in_channel
                   → The bot was never invited: /invite @YourApp
```

`PASS` means the credential works right now. `SKIP` means nothing is configured for that check — not an error. `FAIL` always comes with the fix. The checks, by name: `groq`, `anthropic`, `bedrock`, `speech`, `gmail`, `linear`, `slack`, `github`, `dynamodb`, `memory`. Run a subset with `handoff doctor gmail slack`.

The **Test** button beside each row on the Credentials page runs the same check, so *connected* in the UI means exactly what a `PASS` means in the terminal.

## Embedded in a host

If Handoff runs inside another agent runtime that already holds the user's OAuth tokens, skip all of this: it uses the host's already-authenticated tools rather than keeping a second copy of every credential, and asks its questions through the host's own human-input channel. See [Architecture](/docs/architecture).
