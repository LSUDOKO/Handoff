# Handoff — Deployment Guide

## Deployment Targets

| Target | When | Purpose |
|---|---|---|
| **Local** | Development + fallback | `uvicorn ui.server:app --reload` |
| **AgentCore Runtime** | Production + live demo | Serverless background agent |
| **UI on EC2/ECS/local** | Always | FastAPI decision screen |

---

## 1. Local Development

### 1.1 Setup
```bash
git clone https://github.com/YOUR_USERNAME/handoff.git
cd handoff

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your keys
```

### 1.2 Run locally
```bash
# Terminal 1: Start the UI
cd ui && uvicorn server:app --reload --port 8000

# Terminal 2: Run the agent locally (manual trigger)
python scripts/run_local.py --workflow inbox_triage --trigger manual
```

### 1.3 Local run script (`scripts/run_local.py`)
```python
#!/usr/bin/env python3
"""Run Handoff workflows locally without AgentCore."""

import argparse
import json
from handoff.config import get_model
from handoff.graph.factory import build_inbox_triage_graph

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", default="inbox_triage")
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()
    
    model = get_model()
    
    if args.workflow == "inbox_triage":
        graph = build_inbox_triage_graph(model)
        result = graph.invoke({
            "trigger_type": args.trigger,
        })
        print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
```

---

## 2. AWS Account Setup

### 2.1 IAM Policy (minimum required)
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock-agentcore:*"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:CreateTable"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/handoff_*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "sns:Publish",
                "ses:SendEmail"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "events:PutRule",
                "events:PutTargets"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:PutImage",
                "ecr:CreateRepository"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "*"
        }
    ]
}
```

### 2.2 Bedrock Model Access
1. Go to AWS Console → Amazon Bedrock → Model access
2. Request access to:
   - `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (primary)
   - `us.amazon.nova-pro-v1:0` (fallback)
3. Wait for approval (usually instant)

### 2.3 DynamoDB Tables
```python
# infra/dynamodb_setup.py
import boto3

dynamodb = boto3.resource('dynamodb')

# Workflow configs table
dynamodb.create_table(
    TableName='handoff_workflows',
    KeySchema=[{'AttributeName': 'workflow_id', 'KeyType': 'HASH'}],
    AttributeDefinitions=[{'AttributeName': 'workflow_id', 'AttributeType': 'S'}],
    BillingMode='PAY_PER_REQUEST'
)

# Audit log table
dynamodb.create_table(
    TableName='handoff_audit',
    KeySchema=[
        {'AttributeName': 'workflow_id', 'KeyType': 'HASH'},
        {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
    ],
    AttributeDefinitions=[
        {'AttributeName': 'workflow_id', 'AttributeType': 'S'},
        {'AttributeName': 'timestamp', 'AttributeType': 'S'}
    ],
    BillingMode='PAY_PER_REQUEST'
)

# Pending interrupts table
dynamodb.create_table(
    TableName='handoff_interrupts',
    KeySchema=[{'AttributeName': 'interrupt_id', 'KeyType': 'HASH'}],
    AttributeDefinitions=[{'AttributeName': 'interrupt_id', 'AttributeType': 'S'}],
    BillingMode='PAY_PER_REQUEST'
)
```

---

## 3. AgentCore Runtime Deployment

### 3.1 Dockerfile
```dockerfile
FROM python:3.12-slim

# AgentCore Runtime uses ARM64
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY ui/ ./ui/
COPY workflows/ ./workflows/

# Set Python path
ENV PYTHONPATH=/app/src

# AgentCore Runtime expects port 8080
EXPOSE 8080

# Entrypoint
CMD ["python", "-m", "handoff.app"]
```

### 3.2 Build & Push to ECR
```bash
# Create ECR repository
aws ecr create-repository --repository-name handoff --region us-east-1

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build ARM64 image
docker buildx build \
  --platform linux/arm64 \
  -t <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/handoff:latest \
  --push .
```

### 3.3 Deploy to AgentCore
```bash
# Install the AgentCore toolkit
pip install bedrock-agentcore-starter-toolkit

# Configure
agentcore configure \
  --entrypoint src/handoff/app.py \
  --region us-east-1 \
  --image <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/handoff:latest

# Deploy
agentcore launch

# Verify
agentcore status

# Test invoke
agentcore invoke '{"type": "tick"}'
```

### 3.4 Enable Memory
```bash
# Configure AgentCore Memory
agentcore memory configure \
  --strategy user_preference \
  --strategy semantic
```

### 3.5 Enable Observability
```bash
# Enable OTEL export to CloudWatch
export STRANDS_OTEL_ENABLE=true
export STRANDS_OTEL_EXPORTER=cloudwatch
```

---

## 4. Scheduled Trigger (EventBridge)

```python
# infra/eventbridge_setup.py
import boto3

events = boto3.client('events')

# Create a rule that fires every weekday at 8am EST
events.put_rule(
    Name='handoff-inbox-triage-morning',
    ScheduleExpression='cron(0 13 ? * MON-FRI *)',  # 8am EST = 13:00 UTC
    State='ENABLED',
    Description='Trigger Handoff inbox triage workflow every weekday morning'
)

# Target: invoke the AgentCore Runtime agent
events.put_targets(
    Rule='handoff-inbox-triage-morning',
    Targets=[{
        'Id': 'handoff-agent',
        'Arn': 'arn:aws:bedrock-agentcore:...',  # AgentCore Runtime ARN
        'Input': '{"type": "tick", "workflow_id": "inbox-triage-morning"}'
    }]
)
```

---

## 5. Environment Variables (`.env.example`)

```env
# AWS
AWS_REGION=us-east-1
AWS_PROFILE=handoff

# Bedrock
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_FALLBACK_MODEL_ID=us.amazon.nova-pro-v1:0

# DynamoDB
DDB_WORKFLOWS_TABLE=handoff_workflows
DDB_AUDIT_TABLE=handoff_audit
DDB_INTERRUPTS_TABLE=handoff_interrupts

# Notifications
NOTIFY_CHANNEL=slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SNS_TOPIC_ARN=

# UI
UI_BASE_URL=http://localhost:8000

# AgentCore
AGENTCORE_ENDPOINT=

# Observability
STRANDS_OTEL_ENABLE=true
STRANDS_OTEL_EXPORTER=console

# MCP (optional — mock tools used if not set)
GMAIL_OAUTH_TOKEN=
LINEAR_API_KEY=
SLACK_BOT_TOKEN=
```

---

## 6. Live Demo Link

For the submission, you need a publicly accessible demo. Options:

### Option A: AgentCore Runtime + hosted UI (ideal)
- Agent runs on AgentCore Runtime
- UI runs on EC2/ECS/Lightsail with a public IP
- Submit the UI URL as the live demo link

### Option B: Local + ngrok (backup)
```bash
# Run locally
uvicorn ui.server:app --port 8000

# Expose via ngrok
ngrok http 8000
# Submit the ngrok URL as the live demo link
```

### Option C: Deploy UI to Vercel/Netlify (lightweight)
- Export the FastAPI app as a serverless function
- Agent still runs on AgentCore Runtime
- UI is globally accessible

**A working demo beats a broken cloud deploy. Get Option B working first, then upgrade to Option A if time permits.**

---

## 7. Pre-Flight Checklist

Before recording the demo video:
- [ ] Agent runs locally with mock tools → correct classification + interrupt
- [ ] Decision screen renders correctly from interrupt payload
- [ ] Approve/Edit/Decline buttons work and resume the workflow
- [ ] Audit log shows entries with "agent" and "human" decision sources
- [ ] (If deployed) AgentCore Runtime responds to invoke
- [ ] (If deployed) Scheduled trigger fires correctly
- [ ] OTEL trace is visible (console or CloudWatch)
- [ ] Live demo URL is accessible
