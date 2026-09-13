# Workflows

A workflow is a readable, versionable description of a recurring job: when it wakes up, which integrations it uses, what it may do on its own, and where it has to stop and ask you. This page is the config format, the five templates, and how workflows move between machines.

## From a sentence

You do not usually write a workflow by hand. In Chat, or on the Talk page, describe the chore:

> Every weekday at 8am, triage my inbox. Real asks from teammates become Linear tickets. Newsletters get archived. Mail from my manager gets a draft reply. Anything you're not sure about, ask me.

The assistant checks which integrations you have, writes the config, and shows you a plain-language preview — when it runs, what it handles silently, what it will ask about — before saving anything. In the typed chat a saved workflow starts as a **draft** you can review; by voice it is saved **active** so it is ready to run.

## The config

Every workflow is one JSON object. This is the shipped inbox-triage template, trimmed:

```json
{
  "workflow_id": "inbox-triage-morning",
  "name": "Morning Inbox Triage",
  "description": "Triage unread mail before standup: file real asks, archive noise, draft replies to my manager, and ask me about anything genuinely unclear.",
  "status": "active",
  "trigger": { "type": "cron", "schedule": "0 8 * * 1-5", "timezone": "America/New_York" },
  "mcp_tools": ["gmail", "linear", "slack"],
  "steps": [ ... ],
  "completion": { "notify": "slack", "channel": "#daily-triage", "message": "..." },
  "memory": { "learn_from_decisions": true, "preference_key": "inbox_triage_rules" },
  "confidence_threshold": 0.7
}
```

### Top-level fields

| Field | Meaning |
|---|---|
| `workflow_id` | Stable identifier, used in URLs, the CLI and schedules. Lower-case with hyphens. |
| `name` | What the UI shows. |
| `description` | The sentence you would say to a colleague. It is also part of the executor's instructions for the run. |
| `status` | `active` runs on its trigger; `paused` keeps the schedule but does not fire; `draft` has not been switched on yet. |
| `confidence_threshold` | Optional. Overrides `CONFIDENCE_THRESHOLD` for this workflow only. A read-only monitor can be bolder than one that files tickets. |

### `trigger`

| Field | Meaning |
|---|---|
| `type` | `cron`, `webhook`, `event` or `manual`. |
| `schedule` | Five-field cron for `cron` triggers: minute, hour, day of month, month, day of week. Validation rejects anything else. |
| `timezone` | An IANA zone such as `America/New_York`. Defaults to `UTC`. The welcome screen asks for yours so generated schedules are right. |
| `path` | For webhooks: the path the signal arrives on. |

A webhook or event trigger whose payload is empty never reaches the executor — the graph's `trigger → executor` edge carries that condition, so an empty signal costs no model call.

### `mcp_tools`

The integrations this workflow may use, by registry name: `gmail`, `linear`, `slack`, `github`, `web` (a credential-free page fetcher), `browser` and `code_interpreter` (AgentCore's built-ins). An unknown name is a validation error; a known one without credentials is a warning, so you can design ahead of connecting.

### `steps`

A list of objects the executor reads as its plan. The templates use a small vocabulary:

- A fetch step: `{"id": "fetch_emails", "action": "gmail.search_threads", "params": {"query": "is:unread newer_than:12h", "max_results": 20}}`
- A recall step: `{"id": "recall", "action": "memory.recall_preferences", "params": {"preference_key": "inbox_triage_rules"}}`
- A classify step: `{"id": "classify", "action": "llm_classify", "input_from": "fetch_emails", "categories": ["teammate_request", "newsletter", "manager", "automated", "ambiguous"]}`
- Automatic actions: `{"id": "auto_actions", "rules": [{"category": "newsletter", "action": "gmail.archive", "auto": true}, ...]}`
- The human gate: `{"id": "human_gate", "category": "ambiguous", "action": "interrupt", "present": ["email_summary", "sender", "suggested_action", "reasoning", "confidence"], "options": ["file_ticket", "archive", "draft_reply", "skip"]}`

A workflow with no `human_gate` step validates with a warning: it will act entirely on its own, which is fine for read-only work and risky for anything irreversible.

### `completion`

Where the run reports when it finishes. `notify` is `console`, `slack` or `sns`; `channel` is the Slack channel; `message` is a template that may use `{auto_count}`, `{interrupt_count}` and `{memory_count}` — how many items it handled alone, how many you decided, how many it handled from rules you set earlier.

### `memory`

`learn_from_decisions` turns each of your answers into a rule; `preference_key` names the bucket those rules live in, so a Slack digest never applies rules learned from your inbox.

## Validation

Every path to a saved workflow — the chat, the Talk page, a workspace import — runs the same validation. Blocking errors: a missing `workflow_id`, `name`, `trigger` or `steps`; an unknown trigger type; a cron trigger without a schedule or with the wrong number of fields; an unknown integration; anything the schema rejects. Warnings: no integrations, an unconfigured integration, no human gate.

## The five templates

They are loaded into your workspace the first time Handoff starts, ready to run or edit:

| Template | Trigger | Uses |
|---|---|---|
| Morning Inbox Triage | weekdays 08:00 | gmail, linear, slack |
| PR Review Triage | weekdays 09:00 | github, slack |
| Weekly Competitor Pricing Watch | Mondays 09:00 | web, browser, slack |
| Slack Channel Digest | weekdays 18:00 | slack, linear |
| Meeting Follow-up | event | gmail, linear |

The source files are in `src/handoff/workflows/`. The competitor watch reads a live page through the credential-free `web` server, so a fresh clone can exercise one real integration with no key at all.

## Running

**Run now** on the overview or the workflow page starts a run and streams a live feed under the row. From the terminal, `handoff run <workflow_id>` starts one and returns when it completes or stops for you. Schedules fire from an in-process scheduler while `handoff serve` or the desktop app is open; for schedules that must fire when your laptop is shut, see [Deploy](/docs/deploy).

## `workspace.yml`: export and import

A workspace — its workflows, custom skills, custom agents and tool servers — renders as one YAML document you can edit, version and hand to a teammate. Credentials are never in it.

```bash
handoff workspace export workspace.yml        # the document
handoff workspace export team.zip             # a bundle: the document plus one file per skill and agent
handoff workspace import workspace.yml        # or team.zip
```

The same three actions are on the workspace's Settings page. Import has *the file is the truth* semantics: things the file names are created or updated, and things the workspace had that the file no longer lists are removed. Edit the YAML in place and save it, and the workspace follows.
