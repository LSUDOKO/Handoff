# Deploy

On a laptop, Handoff schedules its own runs while the app is open. To make "every weekday at 8am" true when the laptop is shut, deploy the agent to Amazon Bedrock AgentCore Runtime and let EventBridge own the schedule. Six scripts, each a few boto3 calls, in a fixed order.

## Two ways to be autonomous

| | Runs where | Schedule owned by | State |
|---|---|---|---|
| **Laptop** | `handoff serve` or `handoff desktop` | an in-process scheduler that wakes every 30 seconds while the app is open | JSON files in `HANDOFF_STATE_DIR` |
| **AgentCore** | a container on AgentCore Runtime | EventBridge Scheduler → Lambda → the runtime | one DynamoDB table and AgentCore Memory |

Both run identical code. The deployed one is told to use DynamoDB and AgentCore Memory through its environment at launch, because a container's filesystem is ephemeral and a deployment that keeps state on it forgets every run between calls.

## Prerequisites

- The AWS CLI, with credentials from `aws configure` or `aws sso login`.
- Docker with `buildx`. AgentCore Runtime requires `linux/arm64`; on an x86 machine install QEMU once: `docker run --privileged --rm tonistiigi/binfmt --install arm64`.
- `pip install -e ".[bedrock,agentcore]"` for boto3 and the runtime SDK.
- `AWS_REGION` set in `.env` to a region where Bedrock and AgentCore are available.

```bash
python infra/deploy_agentcore.py --check
```

The preflight names everything that is missing and stops. Handoff still runs locally without any of it.

## The order

Set these in `.env` **before** deploying, because the runtime reads them at launch:

```bash
USE_DYNAMODB=true
USE_AGENTCORE_MEMORY=true
AGENTCORE_MEMORY_ID=        # filled in by memory_setup.py below
```

Then, from the repository root:

```bash
python infra/dynamodb_setup.py                 # 1  one table, on-demand
python infra/memory_setup.py                   # 2  AgentCore Memory → paste the id into .env
python infra/deploy_agentcore.py               # 3  build arm64 → ECR → Runtime, wait for READY
python infra/iam_setup.py                      # 4  the role EventBridge Scheduler assumes
python infra/lambda_setup.py --runtime-arn <runtime arn from step 3>
python infra/eventbridge_setup.py --target-arn <lambda arn from step 5> --role-arn <role arn from step 4>
```

Each script prints what to do next and is safe to run again.

### 1. DynamoDB: one table

`dynamodb_setup.py` creates a single table (`DDB_TABLE`, default `handoff`) with a composite key: `pk` is the collection name — `runs`, `workflows`, `interrupts`, `chats`, `usage` and the rest — and `sk` is the item's id. Listing a collection is a `Query`, never a `Scan`, and one collection's rows can never be handed to another's model. On-demand billing, so an idle deployment costs nothing. `--delete-legacy` removes the older three-table layout if you have one.

### 2. AgentCore Memory

`memory_setup.py` creates a memory store named `handoff_preferences` with two strategies: user preferences under `/preferences/{actorId}` and semantic memory under `/decisions/{actorId}`. It prints the memory id. The learned rules the gate applies are written here *and* to the local store, so the dashboard reads them whether or not AgentCore is reachable.

### 3. The runtime

`deploy_agentcore.py` creates the ECR repository, logs Docker in, builds the image for `linux/arm64` and pushes it, then hands over to `agentcore_runtime.py`, which creates the execution role (`handoff-runtime`) and the runtime itself through the control-plane API and waits for `READY`. It finishes with two smoke tests: a `status` invocation and one scheduled run of the inbox triage.

The Python `agentcore` CLI is deprecated and its `launch` reports success while launching nothing when its config file is missing — which is why the deployment talks to the API directly. `--skip-build` relaunches from the image already in ECR.

The image is `python:3.12-slim` running `python -m handoff.app` on port 8080. The entrypoint accepts five event shapes: `{"type": "tick", "workflow_id": …}` for a scheduled run, `webhook` with a payload, `decide` with an interrupt id and action, `build` with a message for the assistant, and `status`.

### 4–6. Cron in the cloud

EventBridge Scheduler cannot target AgentCore Runtime; `CreateSchedule` rejects it. So the schedule fires a twelve-line Lambda, `handoff-tick`, which forwards its input unchanged with `InvokeAgentRuntime`. The payload is the same `{"type": "tick", "workflow_id": …}` the runtime accepts from anything else, so the bridge adds no vocabulary of its own.

Two roles, each allowed exactly one thing: `handoff-scheduler` may invoke the function; `handoff-tick` may invoke the runtime. `eventbridge_setup.py` then creates one schedule per active cron workflow, named `handoff-<workflow_id>`, translating the five-field cron and the workflow's timezone into EventBridge's six-field form. `--list` shows what it would create; `--delete <workflow_id>` removes one.

## Regions and model ids

Current Bedrock models are not callable by their bare id. They are reached through a cross-region inference profile whose id carries a geography prefix — `us.`, `apac.`, `eu.` — and the prefix has to match the region you call from: `us.amazon.nova-pro-v1:0` fails from Seoul. Handoff adds the right prefix for `AWS_REGION` automatically, so set the bare id:

```bash
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0          # becomes apac.amazon.nova-pro-v1:0 in ap-northeast-2
BEDROCK_FALLBACK_MODEL_ID=amazon.nova-lite-v1:0
```

An id that already names its geography is passed through, which is how you reach models offered only under `global.` — Claude Sonnet 4.5 among them, outside the US. `aws bedrock list-inference-profiles --region <region>` shows what exists where you are.

Anthropic models on Bedrock are sold through AWS Marketplace and Amazon's own are not. An account that cannot complete a Marketplace agreement gets `AccessDeniedException: … INVALID_PAYMENT_INSTRUMENT` on Claude in *every* region and works fine on Nova. It is a billing state, not a permissions problem, and changing region does not fix it. That is why the default is Nova Pro.

## Budget

The trigger and completer nodes always run on the fallback model; only the executor, where the judgement happens, uses the primary. A full inbox-triage run is roughly 25K tokens.

| Model | Input / output per million tokens |
|---|---|
| Amazon Nova Pro | $0.80 / $3.20 |
| Amazon Nova Lite | $0.06 / $0.24 — about 13× cheaper |
| Amazon Nova Micro | $0.035 / $0.14, text only |

Verify plumbing on Nova Lite and keep Nova Pro for the runs that matter. Speech is cents: Transcribe streaming is $0.024 per minute heard, Polly neural $16 per million characters. DynamoDB on-demand and an idle runtime cost nothing between runs. The **Usage** page attributes tokens and cost to the model that served each call, per run, so the number to report after a real run is there rather than estimated.

## Observability

```bash
STRANDS_OTEL_ENABLE=true
STRANDS_OTEL_EXPORTER=otlp        # console locally; otlp → CloudWatch on AgentCore
```

Every agent turn and tool call becomes a span. The Inspector page shows the same data as a waterfall without leaving the app.

## The site

This documentation and the landing page are static files deployed to Cloudflare Pages. `make site` renders `docs/site/*.md` and the landing page into `site/dist/`; `make site-deploy` publishes it with `wrangler pages deploy site/dist --project-name handoff`. The app itself stays where a Python runtime is: your machine, the desktop window, or AgentCore.
