# Setting Handoff up for real

Getting from "runs on synthetic data" to "triages my actual inbox at 8am".

Work through it in order. After each step run `handoff doctor` — every check
makes a real API call, so a green line means the credential genuinely works,
not merely that the variable is set.

```bash
source .venv/bin/activate
make doctor
```

---

## Step 0 — Which surface are you setting up?

| | Runs where | Who manages credentials | Use when |
|---|---|---|---|
| **Desktop** | `make desktop` — native window | You, in `.env` | Day to day |
| **Web** | `make serve`, port 8000 | You, in `.env` | Demoing, or on a server |
| **Embedded** | Inside another agent runtime | That host, via its own OAuth | You already run an agent platform |
| **AgentCore** | AWS, serverless | AWS + `.env` baked into the image | It should run when your laptop is shut |

The first three run the same code and read the same `.env`; the desktop window is
the web UI in a native frame (WebKitGTK on Linux, WebKit on macOS, WebView2 on
Windows). This guide covers the credentials they share.

---

## Step 1 — Make the reasoning real

Everything else is pointless until the agent is actually thinking. Pick either
provider; both run identical agent code.

### Option A — Groq (free tier, also enables voice)

1. <https://console.groq.com> → **API keys** → **Create key**
2. In `.env`:

```bash
HANDOFF_MODEL_PROVIDER=groq
GROQ_API_KEY=gsk_...
HANDOFF_FAKE_MODEL=false
```

3. `make doctor` — the Groq check also prints your remaining tokens for the
   minute.

Free tier limits (per model): **8,000 tokens/minute, 200,000/day.** A full
triage run is ~25K tokens, so budget ~8 runs a day per model. `qwen/qwen3.8-27b`
is the validated default; `openai/gpt-oss-120b` and `-20b` are separate
buckets you can switch to with `GROQ_MODEL_ID`.

For Handoff to *talk back* in a real voice, accept the Orpheus terms once:
<https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english>.
Until then it uses your browser's built-in voice. Whisper (hearing you) needs
no acceptance.

### Option B — Anthropic API (~2 minutes)

1. Go to <https://console.anthropic.com> → **API keys** → **Create key**
2. In `.env`:

```bash
HANDOFF_MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
HANDOFF_FAKE_MODEL=false
```

3. `python -m handoff.cli doctor anthropic`

### Option C — AWS Bedrock (what the hackathon deployment uses)

1. Install the AWS CLI. On Arch: `sudo pacman -S aws-cli-v2`
2. **IAM → Users → Create user**, attach `AdministratorAccess` for a throwaway
   hackathon account, then **Security credentials → Create access key → CLI**.
3. `aws configure` — key, secret, region, `json`. Keys go here and nowhere else;
   don't paste them into a chat or a file you might commit.
4. In `.env`:

```bash
HANDOFF_MODEL_PROVIDER=bedrock
AWS_REGION=ap-northeast-2      # or whichever region you chose
HANDOFF_FAKE_MODEL=false
```

5. `python -m handoff.cli doctor bedrock`

#### Two things about Bedrock that cost us a day each

**There is no "Model access" page any more.** It was retired; you no longer
request access per model in the console. Bedrock now grants on first use, which
means the only real test is an actual invocation — which is what `doctor` does.

**Anthropic models on Bedrock are sold through AWS Marketplace, and Amazon's
own are not.** If your account cannot complete a Marketplace agreement you get:

```
AccessDeniedException: Model access is denied due to INVALID_PAYMENT_INSTRUMENT
```

This is an account-level billing state, **not** a region or a permissions
problem — changing region does not fix it, and neither does adding a card as
the default payment method if the card is rejected for Marketplace
specifically. Amazon Nova is first-party and on-demand in every Bedrock region,
so it works on an account in that state. That is why the default is Nova Pro:

```bash
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
# BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

#### Model ids carry a region prefix

Current Bedrock models are not callable by their bare id — they are reached
through a *cross-region inference profile*, whose id is prefixed by geography:
`us.`, `apac.`, `eu.`. The prefix has to match the region you call from, so
`us.amazon.nova-pro-v1:0` fails from Seoul. Handoff adds the right prefix for
`AWS_REGION` automatically, so set the bare id and let it resolve:

```bash
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0   # becomes apac.… in ap-northeast-2
```

An id that already names its geography is passed through untouched, which is
how you reach the models offered only under `global.` — Claude Sonnet 4.5 among
them, outside the US. `aws bedrock list-inference-profiles --region <region>`
shows which prefix a given model actually has where you are.

### Verify

```bash
make run            # real reasoning this time
```

The reasoning is now genuinely the model's. It may classify the synthetic
inbox differently from the scripted run — that is the point. The actions are
still mocked; that's Step 2.

---

## Step 2 — Make the inbox real (Gmail)

The heaviest step, because Google's OAuth requires a project.

Handoff asks for the `gmail.modify` scope — read, archive, label, draft. It
cannot send mail, by design.

1. <https://console.cloud.google.com> → create a project
2. **APIs & Services** → **Library** → enable **Gmail API**
3. **OAuth consent screen** → External → add yourself as a test user
4. **Credentials** → **Create credentials** → **OAuth client ID** → Desktop app
5. Download the client JSON
6. Run the OAuth flow once to mint a token with scope
   `https://www.googleapis.com/auth/gmail.modify`
7. `GMAIL_OAUTH_TOKEN=ya29...` in `.env`
8. `python -m handoff.cli doctor gmail` — it prints your address and message
   count, so you know it's your real mailbox

> If you embed Handoff in a host runtime that already holds a Gmail token, skip
> all of this: it uses the host's credential instead. See `handoff.host`.

Then:

```bash
USE_MOCK_TOOLS=false
```

⚠️ **Before the first live run**, narrow the query. The shipped template uses
`is:unread newer_than:12h`; for a first run against a real mailbox, edit the
workflow in the builder (or
[`src/handoff/workflows/inbox_triage.json`](../src/handoff/workflows/inbox_triage.json))
to something like `is:unread newer_than:1h`. The interrupt gate protects you
from *wrong* actions, not from *many* actions. Watch one small batch first.

---

## Step 3 — Make the actions real

### Linear (easiest of the three)

1. Linear → **Settings** → **API** → **Personal API keys** → create one
2. `LINEAR_API_KEY=lin_api_...` in `.env`
3. `python -m handoff.cli doctor linear` — prints your name and email

Note: Linear wants the key raw in the `Authorization` header, with no
`Bearer ` prefix. The doctor check uses the correct form.

### Slack

Either works. A **bot token** is better: it reports real delivery failures,
where a webhook returns 200 for a channel nobody reads.

**Webhook (5 minutes):**
1. <https://api.slack.com/apps> → **Create New App** → From scratch
2. **Incoming Webhooks** → activate → **Add New Webhook to Workspace**
3. `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`

**Bot token (better):**
1. Same app → **OAuth & Permissions**
2. Bot token scopes: `chat:write` (add `channels:read` if a workflow should
   read channels)
3. **Install to Workspace** → copy the `xoxb-...` token
4. `SLACK_BOT_TOKEN=xoxb-...`
5. **Invite the bot to the channel**: `/invite @YourApp` in `#daily-triage` —
   otherwise you get `not_in_channel`
6. `python -m handoff.cli doctor slack`

### GitHub

1. <https://github.com/settings/tokens> → **Fine-grained tokens**
2. Grant **Issues: read & write** and **Pull requests: read** on the repos you
   care about
3. `GITHUB_TOKEN=github_pat_...`
4. `python -m handoff.cli doctor github`

---

## Step 4 — Make it run on its own

Until now you've been pressing **Run now**. This is the part that makes it an
agent rather than a button.

### Local (free, while the machine is awake)

Each workflow carries its own schedule. Run it from cron or a systemd timer:

```cron
0 8 * * 1-5  cd /path/to/Handoff && .venv/bin/handoff run inbox-triage-morning
```

Or let a host runtime's scheduler call `handoff.host.run_in_host`, if you have
one. Either way, `handoff run` is idempotent per invocation — it starts one run
and returns when that run completes or stops for you.

### AWS (runs when your laptop is shut)

```bash
python infra/deploy_agentcore.py --check     # what's missing
python infra/deploy_agentcore.py             # build arm64 → ECR → AgentCore
python infra/memory_setup.py                 # learned rules persist in AWS
python infra/dynamodb_setup.py               # durable audit trail
python infra/eventbridge_setup.py --list     # preview the cron conversion
python infra/eventbridge_setup.py --target-arn <arn> --role-arn <arn>
```

Two things to know:

- **arm64 is required** by AgentCore Runtime. On an x86 machine you need
  `qemu-user-static` installed for the cross-build, or Docker will fail with
  `exec format error`. On Arch: `sudo pacman -S qemu-user-static-binfmt`
- **The EventBridge conversion is not a pass-through.** Unix cron
  `0 8 * * 1-5` becomes `cron(0 8 ? * 2-6 *)` — EventBridge counts weekdays
  from 1=Sunday. `--list` shows you the conversion before anything is created.

---

## Step 5 — Use it as a desktop app, by voice

```bash
make desktop     # native window (WebKitGTK / WebKit / WebView2)
```

Turn **Voice on** in the header. From then on:

- a decision that's waiting is read to you when you open it;
- hold the mic on the decision screen and say *archive it*, *file a ticket*,
  *draft a reply* or *leave it* — the phrase is matched locally, no model
  round-trip, and the decision is submitted;
- hold the mic in the builder to describe a workflow instead of typing it;
- when a run finishes or sets something aside, it says so.

Hearing uses Groq Whisper when a key is set, else the browser's speech
recognition (Chrome). Speaking uses Groq Orpheus once its terms are accepted,
else the browser's synthesis. Nothing goes silent because a key is missing.

## Step 6 — Tune how often it asks

One number decides how much it bothers you:

```bash
CONFIDENCE_THRESHOLD=0.7
```

- **Raise it** (0.8) to be asked more often. Sensible for the first week, while
  you're still deciding whether you trust it.
- **Lower it** (0.6) once the learned rules have built up and the questions
  start feeling obvious.

It can also be set per workflow via `confidence_threshold` in the config, so a
read-only monitoring workflow can be bolder than one that files tickets.

Check what it has learned:

```bash
python -m handoff.cli rules
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `No working model provider` | Step 1 incomplete, or `HANDOFF_FAKE_MODEL` is still `true` |
| Bedrock `AccessDenied` | Model access not granted in that region's Bedrock console |
| Gmail `401` | Token expired — they're short-lived. Re-mint it, or embed in a host runtime that refreshes for you |
| Slack `not_in_channel` | The bot was never invited: `/invite @YourApp` |
| Linear `authentication failed` | A `Bearer ` prefix was added; Linear wants the key raw |
| Docker `exec format error` | Cross-building arm64 without qemu installed |
| It asks about everything | Threshold too high, or no rules learned yet |
| Groq `rate_limit_exceeded` | Free tier is 8K tokens/min and 200K/day **per model**. Wait, or switch `GROQ_MODEL_ID` |
| It acts when it shouldn't | Lower `CONFIDENCE_THRESHOLD` and check `handoff rules` for an over-broad rule |

## The safety property, restated

The gate fires **before** the tool runs, so an escalated item has had nothing
done to it. That holds regardless of which credentials are live. The failure
mode to actually watch for is not the agent acting wrongly on an item it asked
about — it's a *learned rule* that's too broad silently handling things you'd
have wanted to see. `handoff rules` lists every rule it is acting on; read it
after the first week.
