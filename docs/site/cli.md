# The CLI

Everything Handoff does is available from a terminal as `handoff <command>`, with `--json` output for scripts. This page explains the conventions; the reference at the end is generated from the installed command tree, so it always lists exactly the commands your version has.

## Invocation

`pip install -e .` puts `handoff` on your path. `python -m handoff.cli` is the same program, useful inside a Makefile or a cron line that cannot rely on an activated environment:

```cron
0 8 * * 1-5  cd /path/to/Handoff && .venv/bin/handoff run inbox-triage-morning
```

The CLI reads the same `.env` as the app, seeds the five template workflows on first use, and writes to the same state directory — so a workflow you build in the browser is the one `handoff run` runs, and a chat you start in the terminal is the one the browser shows.

## Conventions

**Exit codes.** `0` means it worked. `1` means it failed — a model call errored, a service refused. `2` means you asked for something that does not exist: an unknown workflow id, a bad argument.

**`--json`.** Every read-only command prints a table for people by default and a JSON document with `--json`, so `handoff --json workflows list | jq` works the way you expect. Streaming commands print their final event as JSON.

**`--workspace <id>`** scopes a command to one workspace; the default is your default workspace. **`--state-dir <path>`** points at a different state directory, which is how the test suite and a second instance stay out of your data.

**Secrets never print.** `settings show` and `credentials list` show masked values and fingerprints. `credentials set` reads the secret with a hidden prompt, or from an environment variable with `--from-env`, and never echoes it.

## A tour

**Running things.** `run <workflow_id>` starts a run and prints its outcome when it completes or stops for you; `--watch` follows the run's events live — every tool call, every deferral, the decision it asks for — as `HH:MM:SS kind text` lines. `runs` lists recent runs; `inspect <run_id>` is the step table the Inspector page shows: node, kind, name, status, milliseconds.

**Decisions.** `pending` lists what is waiting on you with the agent's confidence and its one-line summary. `decide <interrupt_id> <action> --note "why"` answers one; the note becomes the learner's strongest signal. `activity` is the audit log.

**Talking.** `ask "what is waiting on me"` is one turn with the workspace assistant, streamed. `chat` is the same in a loop; `/new` starts a fresh chat and `/quit` leaves. `build "every weekday at eight, triage my inbox"` turns a sentence into a workflow, `--activate` switches it on and `--run` starts it immediately.

**Voice.** `say "text"` speaks through the configured provider and plays it, or writes a file with `--out`. `listen file.wav` transcribes a recording. `talk --mic` is push-to-talk in the terminal with spoken replies; without a microphone library it takes typed input and still speaks. See [Talk](/docs/talk).

**Workflows and the workspace.** `workflows list` and `workflows show <id>`; `workspace export path.yml` or `path.zip`, `workspace import path`, `workspace list`. See [Workflows](/docs/workflows).

**The platform.** `agents`, `mcp`, `skills`, `memory`, `credentials` and `schedules` mirror the pages of the same names. `mcp call <server> <tool> --args '{...}'` invokes a tool on a live MCP server; `credentials check` runs the doctor check for one provider; `rules` lists what the gate is acting on.

**Operating.** `serve` starts the web UI; `desktop` opens the native window; `doctor` checks every credential with a real call; `settings show` prints the effective configuration, redacted; `usage` shows tokens and cost per model; `version` prints the version. `share` opens a Cloudflare quick tunnel through `cloudflared` when it is installed and prints the public URL. `deploy agentcore` runs the deployment described in [Deploy](/docs/deploy); `deploy site` builds and publishes this site.

## Examples

Run the morning triage and follow it:

```bash
handoff run inbox-triage-morning --watch
```

Answer everything that is waiting the same way:

```bash
handoff pending
handoff decide int_3f9a2c7b1d0e archive --note "cold outreach"
```

Check a fresh machine before the first scheduled run:

```bash
handoff doctor
handoff doctor gmail speech
```

Export a workspace and load it somewhere else:

```bash
handoff workspace export team.zip
handoff workspace import team.zip
```

Shell completion, for bash, zsh or fish:

```bash
handoff completion zsh > ~/.zfunc/_handoff
```
