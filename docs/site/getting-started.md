# Getting started

Handoff turns a sentence into a scheduled workflow, runs it unattended, and stops to ask you only about the things it genuinely cannot judge. This page gets you from a clone to a running workflow in about ten minutes — offline first, then with a real model.

## What you need

- Python 3.12. The project is developed and tested on 3.12; older versions are not supported.
- Git.
- Node.js, only if you want the Gmail integration — its MCP server runs under `npx`.
- Nothing from AWS yet. Everything below runs with no account and no key.

## Install

Clone the repository and install it into a virtual environment. The extras pull in the pieces you are likely to want on a laptop: the Groq provider, the native desktop window, and a credential-free web-fetch MCP server.

```bash
git clone https://github.com/LSUDOKO/Handoff && cd Handoff
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,groq,desktop,web]"
```

`pip install -e` gives you the `handoff` command on your path. `python -m handoff.cli` is the same thing if you prefer not to rely on the script.

Other extras, when you need them: `anthropic` (the Anthropic API as a provider), `bedrock` (boto3 and the Transcribe streaming SDK, for Bedrock reasoning and AWS speech), `agentcore` (the runtime SDK, only for deploying), and `voice` (`sounddevice`, for recording from the microphone in the terminal or the desktop window).

## The `.env` file

Every setting Handoff reads comes from the environment, and `.env` is where you keep them. Start from the example:

```bash
cp .env.example .env
```

The defaults are chosen so that the whole product runs offline with synthetic data: `USE_MOCK_TOOLS=true` gives the agent a scripted inbox and mocked integrations, and `HANDOFF_STATE_DIR=.handoff-state` keeps runs, decisions and learned rules in JSON files beside the code, where you can read and delete them.

The settings you will touch first:

| Setting | What it does |
|---|---|
| `HANDOFF_MODEL_PROVIDER` | `bedrock`, `anthropic` or `groq`. The agent code is identical; only the model object differs. |
| `HANDOFF_FAKE_MODEL` | `true` runs a deterministic scripted model — no calls, no keys. |
| `USE_MOCK_TOOLS` | `true` means a synthetic inbox and mocked actions. Set `false` when your credentials are real. |
| `CONFIDENCE_THRESHOLD` | Below this the agent stops and asks instead of acting. `0.7` by default. |
| `UI_PORT` | Where `handoff serve` listens. `8000`. |

`.env` is gitignored. Never commit it.

## First run, offline

The demo runs the inbox-triage workflow end to end on the scripted model: it works the inbox, stops on the items it cannot call, answers them for you, then runs again to show that it no longer asks.

```bash
make demo
```

Under the hood that is `python scripts/run_local.py --demo --offline`. To run a single workflow once from the command line:

```bash
HANDOFF_FAKE_MODEL=true handoff run inbox-triage-morning
```

The output is the run's outcome as JSON: how many items it handled alone, how many are waiting on you, and the interrupt ids you can answer with `handoff decide`.

## Make the reasoning real

Pick one provider. Groq has a free tier and needs one key, so it is the fastest way to see a real model think.

```bash
# .env
HANDOFF_MODEL_PROVIDER=groq
GROQ_API_KEY=gsk_...
HANDOFF_FAKE_MODEL=false
```

Then check it:

```bash
handoff doctor
```

Every line `doctor` prints is the result of a real call, not a check that a variable is set. `PASS` means the credential works; `SKIP` means nothing is configured for that check; `FAIL` comes with the fix on the next line. You can run a subset: `handoff doctor groq speech`.

Bedrock is what the AgentCore deployment uses. Set `HANDOFF_MODEL_PROVIDER=bedrock` and `AWS_REGION`, make sure `aws configure` has run, and `handoff doctor bedrock` will make one tiny invocation. Model ids are resolved to the right cross-region inference profile for your region automatically; see [Deploy](/docs/deploy) for the details that bite.

## Open the app

```bash
handoff serve        # http://localhost:8000
handoff desktop      # the same UI in a native window
```

The first visit is a welcome screen that asks for one thing cron cannot live without: your timezone. After that you land on the workspace overview — latest runs, workflows, what is waiting on you.

Five workflows ship as templates and are loaded into your workspace the first time Handoff starts: Morning Inbox Triage, PR Review Triage, Weekly Competitor Pricing Watch, Slack Channel Digest and Meeting Follow-up. Press **Run now** on any of them and a live feed appears under the row as the agent works.

The desktop window is the web UI in a native frame — WebKitGTK on Linux, WebKit on macOS, WebView2 on Windows. It remembers its size and position, reopens on the page you left, and once onboarding is done it opens on the [Talk](/docs/talk) page.

## Where things live

```
.handoff-state/     runs, decisions, audit log, learned rules, chats — JSON, one file per collection
.env                your settings and keys
src/handoff/workflows/   the five templates, as JSON
```

Delete `.handoff-state` to start over; `make clean` does that and clears caches.

## Where to go next

- [Talk](/docs/talk) — speak to it and watch it work.
- [Workflows](/docs/workflows) — the config format, and how to build one from a sentence.
- [The gate](/docs/the-gate) — the one number that decides how often it asks.
- [Integrations](/docs/integrations) — connecting Gmail, Linear, Slack and GitHub.
