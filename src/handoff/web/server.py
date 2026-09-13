# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Handoff's web surface: the log, the builder chat, and the decision screen.

FastAPI + HTMX + Jinja2, deliberately: no build step, no node_modules, no
bundler. `uvicorn handoff.web.server:app` and it runs.

The decision screen is the one that matters. Everything else is reporting.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

UI_DIR = Path(__file__).resolve().parent

from fastapi import (  # noqa: E402
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from handoff import (  # noqa: E402
    config,
    daemon,  # noqa: E402
    events,
)
from handoff.agents.builder import BuilderSession  # noqa: E402
from handoff.agents.executor import run_workflow, submit_decision  # noqa: E402
from handoff.memory.store import list_preferences  # noqa: E402
from handoff.models import InterruptPayload, WorkflowRun  # noqa: E402
from handoff.platform import (  # noqa: E402
    agents_registry,  # noqa: E402
    marketplace,
)
from handoff.platform import credentials as creds  # noqa: E402
from handoff.platform import skills as skills_mod  # noqa: E402
from handoff.platform import usage as usage_mod  # noqa: E402
from handoff.platform.bootstrap import bootstrap  # noqa: E402
from handoff.platform.models import CustomAgent, MCPServerConfig, Workspace  # noqa: E402
from handoff.store import get_store  # noqa: E402
from handoff.tools.mcp_discovery import validate_config_dict  # noqa: E402
from handoff.tools.scheduler import describe_schedule  # noqa: E402
from handoff.tools.voice import (  # noqa: E402
    decision_prompt,
    parse_command,
    speak,
    stt_available,
    transcribe,
)
from handoff.tools.workflow_store import load_example_workflows  # noqa: E402
from handoff.web import nav  # noqa: E402

config.configure_observability()

app = FastAPI(title="Handoff", description="Describe it. Hand it off. It runs.")
app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(UI_DIR / "templates"))

#: Runs in flight, by workflow id — so "Run now" twice doesn't start two.
_RUNNING: dict[str, str] = {}


def _run_in_background(workflow_id: str, trigger: str = "manual") -> str:
    """Start a run on a thread and return its run id immediately.

    The row swaps back at once with a live panel subscribed to the run's
    events; the person watches it work instead of waiting on a spinner.
    """
    from handoff.agents.executor import WorkflowRunner
    from handoff.models import TriggerType, WorkflowRun

    store = get_store()
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(workflow_id)

    run = WorkflowRun(workflow_id=workflow_id, trigger_type=TriggerType.MANUAL)
    store.save_run(run)
    _RUNNING[workflow_id] = run.run_id

    def target() -> None:
        try:
            WorkflowRunner(workflow)._start_existing(run, trigger)
        except Exception as exc:  # the runner already recorded the failure
            print(f"[handoff] background run failed: {exc}")
        finally:
            _RUNNING.pop(workflow_id, None)

    threading.Thread(target=target, name=f"run-{run.run_id}", daemon=True).start()
    return run.run_id


#: One Builder conversation per browser session id. The Builder is stateful by
#: design — it asks follow-up questions — so the thread has to survive between
#: requests.
_SESSIONS: dict[str, BuilderSession] = {}

DECIDED_LABEL = {"agent": "Handoff", "human": "You", "memory": "Your rule"}

#: Action names are written for the model's tool schema, not for people.
#: Every user-facing surface goes through `action_phrase` instead.
ACTION_PHRASE = {
    "file_ticket": "filing a ticket",
    "archive": "archiving it",
    "draft_reply": "drafting a reply",
    "reply": "drafting a reply",
    "post_to_slack": "posting it to Slack",
    "skip": "leaving it alone",
    "": "what to do",
}

OPTION_COPY = {
    "file_ticket": ("File a ticket", "Creates it in Linear, tagged inbox"),
    "archive": ("Archive it", "Out of the inbox, still searchable"),
    "draft_reply": ("Draft a reply", "Written and saved, not sent"),
    "reply": ("Draft a reply", "Written and saved, not sent"),
    "post_to_slack": ("Post to Slack", "Shares it with the channel"),
    "skip": ("Leave it", "No action, stays unread"),
    "approve_suggested": ("Go with your call", "Do what Handoff suggested"),
}


# --- helpers ---------------------------------------------------------------


def action_phrase(action: str) -> str:
    """Turn a tool-schema action name into something a person would say."""
    return ACTION_PHRASE.get(action or "", (action or "").replace("_", " "))


def _ago(when: datetime | None) -> str:
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _clock(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.strftime("%H:%M:%S")


def _schedule_line(workflow) -> str:
    trigger = workflow.trigger
    if trigger.type.value == "cron" and trigger.schedule:
        described = describe_schedule(trigger.schedule, trigger.timezone or "UTC")
        return described.get("readable", trigger.schedule)
    if trigger.type.value == "webhook":
        return f"on POST {trigger.path or '/hook'}"
    if trigger.type.value == "event":
        return "on event"
    return "manual only"


def _flow_view(workflow, store) -> dict[str, Any]:
    latest = store.latest_run(workflow.workflow_id)
    pending = [
        i
        for i in store.pending_interrupts()
        if i.workflow_id == workflow.workflow_id
    ]
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "description": workflow.description,
        "status": workflow.status.value,
        "mcp_tools": workflow.mcp_tools,
        "schedule_readable": _schedule_line(workflow),
        "last_run": _ago(latest.started_at) if latest else "",
        "last_run_id": latest.run_id if latest else "",
        "run_summary": (latest.summary if latest else workflow.description) or workflow.description,
        "pending_count": len(pending),
    }


def _audit_view(entry) -> dict[str, Any]:
    return {
        "at": _clock(entry.timestamp),
        "action": entry.action.replace("_", " "),
        "item_id": entry.item_id,
        "decision_by": entry.decision_by.value,
        "decided_label": DECIDED_LABEL.get(entry.decision_by.value, entry.decision_by.value),
        "detail": entry.details.get("summary")
        or entry.details.get("detail")
        or entry.details.get("reasoning", ""),
    }


def _context(request: Request, page: str, **extra: Any) -> dict[str, Any]:
    """Everything the shell needs, plus whatever the page adds."""
    store = get_store()
    workspace = extra.pop("workspace", None) or _workspace()
    workspaces = store.list_workspaces()
    path = request.url.path
    # The sidebar unfolds the workspace the URL is about, not the one that
    # happens to be selected — a page about workspace B should not show
    # workspace A expanded.
    active_id = workspace.workspace_id if path.startswith("/platform/") or path.startswith("/memory/") else None
    return {
        "request": request,
        "page": page,
        "settings": config.settings_summary(),
        "workspace": workspace,
        "workspaces": workspaces,
        "nav": nav.build(path, workspaces, active_id),
        "ws_json": json.dumps(
            [
                {"id": w.workspace_id, "name": w.name, "color": getattr(w, "color", "amber")}
                for w in workspaces
            ]
        ),
        "stats": store.stats(),
        "profile": store.get_profile(),
        "scheduler": daemon.get_scheduler().status(),
        "voice_enabled": stt_available(),
        **extra,
    }


def _decision_context(request: Request, payload: InterruptPayload) -> dict[str, Any]:
    threshold = config.CONFIDENCE_THRESHOLD
    workflow = get_store().get_workflow(payload.workflow_id)
    workflow_name = workflow.name if workflow is not None else payload.workflow_id
    if workflow is not None and workflow.confidence_threshold:
        threshold = workflow.confidence_threshold

    confidence = payload.agent_analysis.confidence
    # Why the gate stopped. The threshold is the usual reason, but the agent
    # can also flag an item outright — irreversible, or outside its brief —
    # and then a confident number next to "needs 70%" reads as a contradiction.
    if confidence < threshold:
        gate_kind = "threshold"
    elif "rule" in (payload.reason or "").lower():
        gate_kind = "rule"
    else:
        gate_kind = "flagged"
    suggested = payload.agent_analysis.suggested_action

    options = []
    for value in payload.options:
        if value == "approve_suggested" and not suggested:
            continue
        label, hint = OPTION_COPY.get(value, (value.replace("_", " ").capitalize(), ""))
        options.append(
            {
                "value": value,
                "label": label,
                "hint": hint,
                "suggested": value == suggested,
            }
        )

    siblings = [
        p
        for p in get_store().interrupts_for_run(payload.run_id)
        if p.interrupt_id != payload.interrupt_id and not p.resolved
    ]

    resolved_line = ""
    if payload.resolved and payload.decision:
        chosen = OPTION_COPY.get(payload.decision.chosen_action, ("", ""))[0]
        if siblings:
            resolved_line = (
                f"{chosen or payload.decision.chosen_action}. "
                f"{len(siblings)} more {'is' if len(siblings) == 1 else 'are'} waiting — "
                f"the run resumes once they're all answered."
            )
        else:
            resolved_line = (
                f"{chosen or payload.decision.chosen_action}. The run picked up where "
                f"it left off, and Handoff will handle the next one like this itself."
            )

    return _context(
        request,
        "decision",
        payload=payload,
        workflow_name=workflow_name,
        gate_kind=gate_kind,
        options=options,
        confidence_pct=round(confidence * 100),
        threshold_pct=round(threshold * 100),
        filled_segments=round(confidence * 20),
        clears=confidence >= threshold,
        resolved_line=resolved_line,
        siblings=siblings,
        voice_prompt=decision_prompt(payload),
        voice_enabled=stt_available(),
    )


templates.env.filters["action_phrase"] = action_phrase


# --- routes ----------------------------------------------------------------


#: Which workspace this browser session is looking at.
_ACTIVE_WORKSPACE: dict[str, str] = {}


def _workspace() -> Workspace:
    store = get_store()
    chosen = _ACTIVE_WORKSPACE.get("id")
    if chosen:
        found = store.get_workspace(chosen)
        if found is not None:
            return found
    return store.default_workspace()


def _reconcile_runs() -> None:
    """A run that says "running" after a restart is not running.

    Threads don't survive the process. Left alone, the row shows a pulsing
    RUNNING badge forever and the sidebar counts it as busy. Mark it failed
    with a reason a person can act on, rather than pretending.
    """
    from handoff.models import RunStatus

    store = get_store()
    for run in store.list_runs():
        if run.status == RunStatus.RUNNING and run.run_id not in _RUNNING.values():
            run.status = RunStatus.FAILED
            run.summary = run.summary or "Interrupted: Handoff was restarted while this run was in progress."
            run.finished_at = datetime.now(UTC)
            store.save_run(run)
            events.emit(run.run_id, "failed", "interrupted by restart")


@app.on_event("startup")
def _startup() -> None:
    """Bring the install up, then start the scheduler.

    Bootstrap is idempotent, so this runs every start and does nothing the
    second time.
    """
    report = bootstrap()
    new = {k: v for k, v in report.items() if isinstance(v, list) and v}
    if new:
        print(f"[handoff] first-run setup: { {k: len(v) for k, v in new.items()} }")
    _reconcile_runs()
    daemon.get_scheduler().start()
    print("[handoff] scheduler running")


@app.on_event("shutdown")
def _shutdown() -> None:
    daemon.get_scheduler().stop()


COMMON_TIMEZONES = [
    "Pacific/Honolulu", "America/Anchorage", "America/Los_Angeles", "America/Denver", "America/Phoenix",
    "America/Chicago", "America/New_York", "America/Toronto", "America/Vancouver", "America/Mexico_City",
    "America/Bogota", "America/Lima", "America/Santiago", "America/Buenos_Aires", "America/Sao_Paulo",
    "UTC", "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Paris", "Europe/Madrid",
    "Europe/Amsterdam", "Europe/Berlin", "Europe/Zurich", "Europe/Rome", "Europe/Stockholm",
    "Europe/Warsaw", "Europe/Athens", "Europe/Istanbul", "Europe/Moscow", "Europe/Kyiv", "Africa/Cairo",
    "Africa/Lagos", "Africa/Nairobi", "Africa/Johannesburg", "Asia/Jerusalem", "Asia/Dubai", "Asia/Tehran",
    "Asia/Karachi", "Asia/Kolkata", "Asia/Bangkok", "Asia/Jakarta", "Asia/Singapore", "Asia/Hong_Kong",
    "Asia/Shanghai", "Asia/Taipei", "Asia/Seoul", "Asia/Tokyo", "Australia/Perth", "Australia/Sydney",
    "Pacific/Auckland",
]


@app.middleware("http")
async def _onboarding_gate(request: Request, call_next):
    """First run lands on the welcome wizard; everything else waits for it.

    Only page navigations are redirected — the API, static files, SSE and
    the wizard itself pass through — so a half-set-up install is never a
    broken one, just one that asks two questions first.
    """
    path = request.url.path
    if (
        request.method == "GET"
        and not path.startswith(("/welcome", "/static", "/api", "/events", "/health", "/favicon"))
        and "text/html" in request.headers.get("accept", "")
        and not request.headers.get("HX-Request")
    ):
        try:
            if not get_store().get_profile().onboarding_completed:
                return RedirectResponse("/welcome", status_code=303)
        except Exception:
            pass
    return await call_next(request)


@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="welcome.html",
        context=_context(request, "welcome", profile=get_store().get_profile(), timezones=COMMON_TIMEZONES),
    )


@app.post("/welcome")
def welcome_save(
    full_name: str = Form(""), email: str = Form(""), timezone: str = Form("UTC"), locale: str = Form("en-US")
):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    store = get_store()
    profile = store.get_profile()
    profile.full_name = full_name.strip()
    profile.email = email.strip()
    try:
        ZoneInfo(timezone.strip())
        profile.timezone = timezone.strip()
    except (ZoneInfoNotFoundError, ValueError):
        profile.timezone = "UTC"
    profile.locale = locale.strip() or "en-US"
    profile.onboarding_completed = True
    profile.updated_at = datetime.now(UTC)
    store.save_profile(profile)
    return RedirectResponse("/", status_code=303)


@app.post("/welcome/skip")
def welcome_skip():
    store = get_store()
    profile = store.get_profile()
    profile.onboarding_completed = True
    profile.updated_at = datetime.now(UTC)
    store.save_profile(profile)
    return RedirectResponse("/", status_code=303)


@app.get("/")
def home():
    """Land on the workspace, the way you'd open the app in the morning."""
    return RedirectResponse(f"/platform/{_workspace().workspace_id}", status_code=303)


@app.get("/activity", response_class=HTMLResponse)
def dashboard(request: Request):
    """What ran, what it did, and the few things it needs from you."""
    store = get_store()
    pending = store.pending_interrupts()
    return templates.TemplateResponse(
        request=request,
        name="activity.html",
        context=_context(
            request,
            "activity",
            pending=pending,
            pending_views=[_decision_context(request, p) for p in pending],
            workflows=[_flow_view(w, store) for w in store.list_workflows()],
            audit=[_audit_view(e) for e in store.list_audit(limit=40)],
            rules=list_preferences(),
        ),
    )


@app.get("/activity/item/{interrupt_id}", response_class=HTMLResponse)
def activity_item(request: Request, interrupt_id: str):
    payload = get_store().get_interrupt(interrupt_id)
    if payload is None:
        raise HTTPException(404, "That decision no longer exists")
    return templates.TemplateResponse(
        request=request,
        name="_activity_item.html",
        context={**_context(request, "activity"), "d": _decision_context(request, payload)},
    )


@app.post("/activity/{interrupt_id}/decide", response_class=HTMLResponse)
def activity_decide(
    request: Request, interrupt_id: str, action: str = Form(...), note: str = Form("")
):
    """Answer a decision inline from Activity; the card re-renders as decided."""
    store = get_store()
    payload = store.get_interrupt(interrupt_id)
    if payload is None:
        raise HTTPException(404, "That decision no longer exists")
    try:
        submit_decision(interrupt_id, action, note)
    except Exception as exc:
        raise HTTPException(500, f"Could not resume the run: {exc}") from exc
    refreshed = store.get_interrupt(interrupt_id) or payload
    response = templates.TemplateResponse(
        request=request,
        name="_activity_item.html",
        context={**_context(request, "activity"), "d": _decision_context(request, refreshed)},
    )
    response.headers["X-Toast"] = f"Decided: {action.replace('_', ' ')}"
    return response


@app.post("/workflow/{workflow_id}/run", response_class=HTMLResponse)
def run_now(request: Request, workflow_id: str):
    """Run a workflow on demand and swap its row back in with the result."""
    store = get_store()
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(404, f"No workflow '{workflow_id}'")

    run_id = _RUNNING.get(workflow_id) or _run_in_background(workflow_id)

    flow = _flow_view(workflow, store)
    flow["live_run_id"] = run_id
    return templates.TemplateResponse(
        request=request,
        name="_workflow_row.html",
        context={"flow": flow},
        headers={"HX-Trigger": "handoff:ran"},
    )


@app.get("/decide/{interrupt_id}", response_class=HTMLResponse)
def decision_screen(request: Request, interrupt_id: str):
    """One screen. One decision."""
    payload = get_store().get_interrupt(interrupt_id)
    if payload is None:
        raise HTTPException(404, "That decision no longer exists")
    return templates.TemplateResponse(
        request=request, name="decision.html", context=_decision_context(request, payload)
    )


@app.post("/decide/{interrupt_id}", response_class=HTMLResponse)
def make_decision(
    request: Request,
    interrupt_id: str,
    action: str = Form(...),
    note: str = Form(""),
):
    """Apply the human's choice, resume the run, and learn from it."""
    store = get_store()
    payload = store.get_interrupt(interrupt_id)
    if payload is None:
        raise HTTPException(404, "That decision no longer exists")

    try:
        submit_decision(interrupt_id, action, note)
    except Exception as exc:
        print(f"[handoff] resume failed: {exc}")
        raise HTTPException(500, f"Could not resume the run: {exc}") from exc

    refreshed = store.get_interrupt(interrupt_id) or payload
    return templates.TemplateResponse(
        request=request,
        name="_decision_body.html",
        context=_decision_context(request, refreshed),
    )


def _chat_page(request: Request, chat_id: str):
    from handoff.chat import get_chat_service

    svc = get_chat_service()
    chat = svc.get(chat_id)
    if chat is None:
        raise HTTPException(404, "No such chat")
    workspace = get_store().get_workspace(chat.workspace_id) or _workspace()
    _ACTIVE_WORKSPACE["id"] = workspace.workspace_id
    blocks = svc.history(chat_id)
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=_context(
            request,
            "chat",
            workspace=workspace,
            chat=chat,
            chats=[c for c in svc.list(workspace.workspace_id) if c.kind != "voice"],
            blocks=blocks,
            live_turn=svc.is_busy(chat_id),
            templates_list=[
                {"workflow_id": w.workflow_id, "name": w.name, "description": w.description,
                 "tools": w.mcp_tools, "schedule": _schedule_line(w)}
                for w in load_example_workflows()
            ] if not blocks else [],
        ),
    )


@app.get("/chat")
def chat_entry(request: Request):
    """Open the workspace's latest chat, or start its first."""
    from handoff.chat import get_chat_service

    svc = get_chat_service()
    workspace = _workspace()
    chat = svc.latest(workspace.workspace_id) or svc.create(workspace.workspace_id)
    seed = request.query_params.get("seed")
    return RedirectResponse(f"/chat/{chat.chat_id}" + ("?seed=1" if seed else ""), status_code=303)


@app.post("/chat/new")
def chat_new(workspace_id: str = Form("")):
    from handoff.chat import get_chat_service

    workspace = get_store().get_workspace(workspace_id) if workspace_id else None
    chat = get_chat_service().create((workspace or _workspace()).workspace_id)
    return RedirectResponse(f"/chat/{chat.chat_id}", status_code=303)


@app.get("/chat/{chat_id}", response_class=HTMLResponse)
def chat_page(request: Request, chat_id: str):
    return _chat_page(request, chat_id)


@app.post("/chat/{chat_id}/send", response_class=HTMLResponse)
def chat_send(request: Request, chat_id: str, message: str = Form(...)):
    """Append the person's turn and a live placeholder that streams the reply."""
    from handoff.chat import get_chat_service

    try:
        turn = get_chat_service().send(chat_id, message)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "No such chat") from exc
    return templates.TemplateResponse(
        request=request, name="_chat_sent.html", context={"text": message, "turn": turn}
    )


@app.post("/chat/{chat_id}/template/{workflow_id}", response_class=HTMLResponse)
def chat_from_template(request: Request, chat_id: str, workflow_id: str):
    workflow = next((w for w in load_example_workflows() if w.workflow_id == workflow_id), None)
    if workflow is None:
        raise HTTPException(404, "No such template")
    message = (
        f"Set up the '{workflow.name}' template for me: {workflow.description} "
        f"Show me the config and tell me where the human line sits before saving."
    )
    return chat_send(request, chat_id, message)


@app.get("/chat/{chat_id}/events")
def chat_events(chat_id: str, turn: int = 0):
    def stream():
        for event in events.subscribe(f"chat:{chat_id}", replay=True):
            kind = event.get("kind", "note")
            if kind == "keepalive":
                yield ": keepalive\n\n"
                continue
            if turn and int(event.get("turn", 0) or 0) != turn:
                continue
            yield f"event: {kind}\ndata: {json.dumps(event, default=str)}\n\n"
            if kind in ("done", "error"):
                yield "event: end\ndata: {}\n\n"
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/{chat_id}/rename")
def chat_rename(chat_id: str, title: str = Form(...)):
    from handoff.chat import get_chat_service

    get_chat_service().rename(chat_id, title)
    return {"ok": True}


@app.post("/chat/{chat_id}/delete")
def chat_delete(chat_id: str):
    from handoff.chat import get_chat_service

    get_chat_service().delete(chat_id)
    return {"ok": True}


@app.post("/chat/save", response_class=HTMLResponse)
def chat_save(request: Request, config: str = Form(...)):
    """Save the config the assistant just produced."""
    from handoff.models import WorkflowConfig, WorkflowStatus

    try:
        parsed = json.loads(config)
    except json.JSONDecodeError as exc:
        return HTMLResponse(
            f'<div class="message assistant"><div class="callout error">That config is not valid JSON: {exc}</div></div>'
        )

    result = validate_config_dict(parsed)
    if not result["valid"]:
        problems = "".join(f"<li>{e}</li>" for e in result["errors"])
        return HTMLResponse(
            f'<div class="message assistant"><div class="callout warn">I can\'t save that yet:<ul>{problems}</ul></div></div>'
        )

    workflow = WorkflowConfig.model_validate(result["config"])
    workflow.status = WorkflowStatus.ACTIVE
    get_store().save_workflow(workflow)
    from handoff.daemon import sync_schedules

    try:
        sync_schedules()
    except Exception:
        pass
    ws = _workspace().workspace_id
    return HTMLResponse(
        f'<div class="message assistant"><div class="bubble">Saved <b>{workflow.name}</b> and switched it on. '
        f'<a class="text-bright" href="/platform/{ws}/workflows">See it in Workflows</a> — or say "run it" to watch it go.</div></div>'
    )


@app.get("/trace/{run_id}", response_class=HTMLResponse)
def trace_page(request: Request, run_id: str):
    """The reasoning trace for one run: every step, and who decided it."""
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No run '{run_id}'")

    steps = [_audit_view(e) for e in reversed(store.list_audit(run_id, limit=500))]
    status_label = {
        "completed": "done",
        "waiting_on_human": "paused",
        "running": "running",
        "failed": "failed",
    }.get(run.status.value, run.status.value)

    return templates.TemplateResponse(
        request=request,
        name="trace.html",
        context=_context(
            request,
            "trace",
            run=_run_view(run),
            steps=steps,
            status_label=status_label,
        ),
    )


def _run_view(run: WorkflowRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "auto_count": run.auto_count,
        "interrupt_count": run.interrupt_count,
        "memory_count": run.memory_count,
        "summary": run.summary,
    }


# --- live feed ---------------------------------------------------------------


def _sse(run_id: str):
    """Server-sent events for one run ("*" follows every run)."""
    for event in events.subscribe(run_id):
        kind = event.get("kind", "note")
        yield f"event: {kind}\ndata: {json.dumps(event)}\n\n"
        if run_id != "*" and kind in ("completed", "failed", "asked"):
            # The run reached a resting state; let the client close cleanly.
            yield "event: end\ndata: {}\n\n"
            return


@app.get("/events/{run_id}")
def event_stream(run_id: str):
    return StreamingResponse(
        _sse(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/live/{run_id}", response_class=HTMLResponse)
def live_panel(request: Request, run_id: str):
    """The live panel, standalone — the dashboard row embeds this."""
    return templates.TemplateResponse(
        request=request,
        name="_live.html",
        context={"run_id": run_id, "history": events.history(run_id)},
    )


# --- the orb ---------------------------------------------------------------------


def _signal_name(workflow) -> str:
    """A short name for the trigger, the way a person would refer to it."""
    trig = workflow.trigger
    if trig.type.value == "webhook":
        return "webhook"
    if trig.type.value != "cron" or not trig.schedule:
        return "manual"
    parts = trig.schedule.split()
    hour = parts[1] if len(parts) > 1 else "*"
    dow = parts[4] if len(parts) > 4 else "*"
    if dow not in ("*", "1-5", "?"):
        return "weekly"
    try:
        h = int(hour)
    except ValueError:
        return "hourly" if hour.startswith("*/") else "schedule"
    return "morning" if h < 12 else ("afternoon" if h < 17 else "evening")


def _work_card_context(workflow) -> dict[str, Any]:
    described = describe_schedule(workflow.trigger.schedule, workflow.trigger.timezone) if workflow.trigger.schedule else {}
    threshold = workflow.confidence_threshold or config.CONFIDENCE_THRESHOLD
    step_by_tool: dict[str, str] = {}
    for step in workflow.steps:
        action = str(step.get("action", ""))
        if "." in action:
            tool, _, op = action.partition(".")
            step_by_tool.setdefault(tool, op.replace("_", " "))
    agents = [
        {"name": t, "kind": "MCP", "role": step_by_tool.get(t, f"reads and acts through {t}")}
        for t in workflow.mcp_tools
    ]
    agents.append({"name": "executor", "kind": "LLM", "role": f"judges each item; stops for you under {int(threshold * 100)}%"})
    notify = workflow.completion.notify or "console"
    agents.append({"name": "completer", "kind": "SEND", "role": f"{notify} {workflow.completion.channel}".strip() if notify != "console" else "writes the summary"})
    return {
        "workflow": workflow,
        "readable": described.get("readable", workflow.trigger.schedule),
        "threshold_pct": int(threshold * 100),
        "signal_name": _signal_name(workflow),
        "agents": agents,
    }


@app.get("/orb", response_class=HTMLResponse)
def orb_page(request: Request):
    """Speak to the workspace and watch what it does, on one page."""
    from handoff import speech
    from handoff.chat import get_chat_service

    svc = get_chat_service()
    workspace = _workspace()
    chat = svc.voice_chat(workspace.workspace_id)
    store = get_store()
    last_workflow = store.get_workflow(chat.last_workflow_id) if chat.last_workflow_id else None
    last_run = store.get_run(chat.last_run_id) if chat.last_run_id else None
    # The graph is redrawn only while its events are still in memory; a run
    # from before a restart has its trace in the inspector instead.
    run_live = bool(last_run and events.history(last_run.run_id))
    return templates.TemplateResponse(
        request=request,
        name="orb.html",
        context=_context(
            request,
            "orb",
            workspace=workspace,
            chat=chat,
            blocks=svc.history(chat.chat_id)[-12:],
            live_turn=svc.is_busy(chat.chat_id),
            speech=speech.status(),
            pending=[_decision_context(request, p) for p in store.pending_interrupts()][:3],
            last_card=({"source": "voice", **_work_card_context(last_workflow)} if last_workflow else None),
            last_run=last_run if run_live else None,
        ),
    )


@app.get("/api/orb/chat")
def orb_chat_id():
    from handoff.chat import get_chat_service

    workspace = _workspace()
    chat = get_chat_service().voice_chat(workspace.workspace_id)
    return {"chat_id": chat.chat_id, "workspace_id": workspace.workspace_id}


@app.post("/orb/reset")
def orb_reset():
    """Start the spoken conversation over. Workflows and runs it created stay."""
    from handoff.chat import get_chat_service

    workspace = _workspace()
    get_chat_service().reset_voice_chat(workspace.workspace_id)
    return RedirectResponse("/orb", status_code=303)


@app.post("/orb/{chat_id}/send")
def orb_send(chat_id: str, message: str = Form(...)):
    """One spoken (or typed) turn on the voice chat. Returns the turn to follow."""
    from handoff.chat import get_chat_service

    try:
        turn = get_chat_service().send(chat_id, message)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "No such chat") from exc
    return {"turn": turn, "events": f"/orb/{chat_id}/events?turn={turn}"}


@app.get("/orb/{chat_id}/events")
def orb_events(chat_id: str, turn: int = 0):
    return chat_events(chat_id, turn)


@app.get("/orb/card/{workflow_id}", response_class=HTMLResponse)
def orb_card(request: Request, workflow_id: str, source: str = "voice"):
    workflow = get_store().get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(404, "No such workflow")
    return templates.TemplateResponse(
        request=request, name="_work_card.html", context={"request": request, "source": source, **_work_card_context(workflow)}
    )


# --- voice ---------------------------------------------------------------------


@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: Annotated[UploadFile, File()]):
    """Speech → text. The browser records 16 kHz WAV; Transcribe or Whisper hears it."""
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty recording")
    result = transcribe(data, filename=audio.filename or "speech.wav")
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return JSONResponse(result)


@app.post("/api/voice/speak")
def voice_speak(body: dict):
    """Text → speech through Polly, Orpheus, or 204 meaning: use the browser's voice."""
    audio, mime, reason = speak(str(body.get("text", "")), body.get("voice") or None)
    if audio is None:
        return Response(status_code=204, headers={"X-Handoff-Fallback": reason})
    return Response(content=audio, media_type=mime, headers={"Cache-Control": "no-store"})


@app.websocket("/api/voice/stream")
async def voice_stream(websocket: WebSocket):
    """Hear while they are still talking.

    16 kHz Int16 PCM frames come in as binary messages; ``partial`` and
    ``final`` text goes out as they are recognised; a ``{"type": "end"}``
    text message closes the utterance and a ``done`` message carries the
    whole transcript. Only AWS streams; the page falls back to an upload
    when it hears ``unsupported``.
    """
    from handoff import speech
    from handoff.speech import aws

    await websocket.accept()
    if speech.provider() != "aws":
        await websocket.send_json({"type": "unsupported", "provider": speech.provider()})
        await websocket.close()
        return
    try:
        session = await aws.LiveTranscription.open(rate=16000, language=config.TRANSCRIBE_LANGUAGE)
    except Exception as exc:
        await websocket.send_json({"type": "error", "text": str(exc)[:160]})
        await websocket.close()
        return

    async def pump() -> None:
        async for text, partial in session.results():
            await websocket.send_json({"type": "partial" if partial else "final", "text": text})

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.send(message["bytes"])
            elif message.get("text"):
                try:
                    event = json.loads(message["text"])
                except ValueError:
                    event = {}
                if event.get("type") == "end":
                    await session.end()
                    await asyncio.wait_for(pump_task, timeout=15)
                    await websocket.send_json({"type": "done", "text": session.transcript()})
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "text": str(exc)[:160]})
        except Exception:
            pass
    finally:
        pump_task.cancel()
        await session.close()
        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/api/voice/command")
def voice_command(body: dict):
    """Map a spoken phrase to a decision action, without a model round-trip."""
    action = parse_command(str(body.get("text", "")), body.get("options"))
    return JSONResponse({"action": action, "heard": body.get("text", "")})


@app.get("/api/voice/status")
def voice_status():
    from handoff import speech

    return JSONResponse(speech.status())


# --- templates -------------------------------------------------------------------


@app.get("/api/pending")
def api_pending():
    return JSONResponse(
        [p.model_dump(mode="json") for p in get_store().pending_interrupts()]
    )


@app.get("/api/status")
def api_status():
    """What the sidebar polls: pending decisions, runs in flight, provider."""
    store = get_store()
    running = [r for r in store.list_runs() if r.status.value == "running"]
    return {
        "pending": len(store.pending_interrupts()),
        "busy": len(running),
        "scheduler": daemon.get_scheduler().status().get("running", False),
        "provider": config.active_provider(),
        "model": config.active_model_id(),
    }


@app.get("/api/stats")
def api_stats():
    return JSONResponse(get_store().stats())


@app.post("/api/workflows/{workflow_id}/run")
def api_run(workflow_id: str, payload: dict | None = None, wait: bool = False):
    """Run a workflow. ``?wait=true`` blocks for the result; default returns a run id."""
    try:
        if wait:
            return JSONResponse(dict(run_workflow(workflow_id, "webhook", payload)))
        run_id = _RUNNING.get(workflow_id) or _run_in_background(workflow_id, "webhook")
        return JSONResponse({"run_id": run_id, "status": "running", "events": f"/events/{run_id}"})
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/decisions/{interrupt_id}")
def api_decide(interrupt_id: str, body: dict):
    action = body.get("action", "")
    if not action:
        raise HTTPException(400, "An 'action' is required")
    try:
        return JSONResponse(dict(submit_decision(interrupt_id, action, body.get("note", ""))))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/health")
def health():
    return {"app": "handoff", "ok": True, "settings": config.settings_summary()}


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/styles.css", status_code=204)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=config.UI_PORT)


# ============================================================================
# The platform
# ============================================================================


def slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "workspace"


def _humanise_delta(when: datetime | None) -> str:
    return _ago(when) if when else "never"


# --- workspaces -------------------------------------------------------------


@app.post("/workspace/switch")
def workspace_switch(workspace_id: str = Form(...)):
    """Point this browser at a different workspace."""
    if get_store().get_workspace(workspace_id) is not None:
        _ACTIVE_WORKSPACE["id"] = workspace_id
        creds.apply_credentials(workspace_id)
    return Response(status_code=204)


@app.post("/workspace/create", response_class=HTMLResponse)
def workspace_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    icon: str = Form("◆"),
    color: str = Form("amber"),
):
    from handoff.platform.bootstrap import seed_memory_stores

    store = get_store()
    workspace = Workspace(
        name=name.strip(), description=description, icon=icon or "◆", color=color or "amber"
    )
    store.workspaces.put(workspace, "workspace_id")
    seed_memory_stores(workspace.workspace_id)
    _ACTIVE_WORKSPACE["id"] = workspace.workspace_id
    return RedirectResponse(f"/platform/{workspace.workspace_id}", status_code=303)


@app.get("/workspace/export")
def workspace_export():
    """A workspace as portable JSON — without its credentials."""
    payload = marketplace.export_workspace(_workspace().workspace_id)
    name = slug(_workspace().name)
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}-workspace.json"'},
    )


@app.get("/workspace/{workspace_id}/export.yml")
def workspace_export_yaml(workspace_id: str):
    from handoff.platform import workspace_yaml

    workspace = get_store().get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(404, "No such workspace")
    return Response(
        content=workspace_yaml.to_yaml(workspace_id),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{slug(workspace.name)}-workspace.yml"'},
    )


@app.get("/workspace/{workspace_id}/bundle.zip")
def workspace_bundle(workspace_id: str):
    from handoff.platform import workspace_yaml

    workspace = get_store().get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(404, "No such workspace")
    return Response(
        content=workspace_yaml.bundle(workspace_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug(workspace.name)}.zip"'},
    )


@app.post("/workspace/import")
async def workspace_import(request: Request, file: Annotated[UploadFile, File()]):
    from handoff.platform import workspace_yaml

    data = await file.read()
    try:
        result = workspace_yaml.import_document(data, file.filename or "")
    except Exception as exc:
        return _settings_page(request, flash=f"Couldn't import: {exc}", kind="error")
    _ACTIVE_WORKSPACE["id"] = result["workspace_id"]
    return RedirectResponse(f"/platform/{result['workspace_id']}", status_code=303)


@app.post("/workspace/{workspace_id}/remove")
def workspace_remove(workspace_id: str):
    from handoff.platform import workspace_yaml

    try:
        workspace_yaml.remove(workspace_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "No such workspace") from exc
    _ACTIVE_WORKSPACE.pop("id", None)
    response = Response(status_code=204)
    response.headers["X-Toast"] = "Workspace removed"
    return response


def _edit_page(request: Request, workspace_id: str, text: str = "", errors=None, saved: str = ""):
    from handoff.platform import workspace_yaml

    workspace = _select_workspace(workspace_id)
    return templates.TemplateResponse(
        request=request,
        name="workspace_edit.html",
        context=_context(
            request,
            "edit",
            workspace=workspace,
            text=text or workspace_yaml.to_yaml(workspace_id),
            doc=workspace_yaml.document(workspace_id),
            errors=errors or [],
            saved=saved,
        ),
    )


@app.get("/platform/{workspace_id}/edit", response_class=HTMLResponse)
def workspace_edit(request: Request, workspace_id: str):
    return _edit_page(request, workspace_id)


@app.post("/platform/{workspace_id}/edit", response_class=HTMLResponse)
def workspace_edit_save(request: Request, workspace_id: str, text: str = Form(...)):
    from handoff.platform import workspace_yaml

    _select_workspace(workspace_id)
    parsed = workspace_yaml.parse(text)
    if not parsed["valid"]:
        items = "".join(f"<li>{e}</li>" for e in parsed["errors"])
        return HTMLResponse(
            f'<div class="callout error"><b>Not saved.</b><ul style="list-style: disc; padding-inline-start: var(--size-5)">{items}</ul></div>'
        )
    counts = workspace_yaml.apply(workspace_id, parsed["payload"])
    response = HTMLResponse(
        f'<div class="callout">Saved — {counts["workflows"]} workflows, {counts["skills"]} skills, '
        f'{counts["agents"]} agents, {counts["tool_servers"]} tool servers'
        + (f', {counts["removed"]} removed' if counts["removed"] else "")
        + ".</div>"
    )
    response.headers["X-Toast"] = "workspace.yml saved"
    return response


# --- workflows --------------------------------------------------------------


@app.get("/platform", response_class=HTMLResponse)
def platform_page(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="workflows.html",
        context=_context(
            request,
            "platform",
            workflows=[_flow_view(w, store) for w in store.list_workflows()],
        ),
    )


def _select_workspace(workspace_id: str) -> Workspace:
    store = get_store()
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(404, f"No workspace '{workspace_id}'")
    _ACTIVE_WORKSPACE["id"] = workspace_id
    return workspace


def _trigger_views(workflows) -> list[dict[str, Any]]:
    views = []
    for w in workflows:
        kind = w.trigger.type.value
        views.append(
            {
                "type": kind,
                "readable": _schedule_line(w) if kind == "cron" else kind.replace("_", " "),
                "workflow": w.name,
            }
        )
    return views


@app.get("/platform/{workspace_id}", response_class=HTMLResponse)
def workspace_overview(request: Request, workspace_id: str):
    """The workspace at a glance: latest runs, workflows, triggers, agents."""
    from handoff.platform import credentials as creds

    workspace = _select_workspace(workspace_id)
    store = get_store()
    workflows = store.list_workflows()
    return templates.TemplateResponse(
        request=request,
        name="platform.html",
        context=_context(
            request,
            "overview",
            workspace=workspace,
            workflows=[_flow_view(w, store) for w in workflows],
            runs=_run_rows(store, limit=4),
            triggers=_trigger_views(workflows),
            agents=store.custom_agents.all(),
            credentials=[c for c in creds.catalogue() if c.get("connected")][:6],
        ),
    )


# --- schedules --------------------------------------------------------------


def _schedule_view(schedule, store) -> dict[str, Any]:
    workflow = store.get_workflow(schedule.workflow_id)
    described = describe_schedule(schedule.cron, schedule.timezone)
    return {
        "schedule_id": schedule.schedule_id,
        "workflow_id": schedule.workflow_id,
        "workflow_name": workflow.name if workflow else schedule.workflow_id,
        "cron": schedule.cron,
        "timezone": schedule.timezone,
        "enabled": schedule.enabled,
        "run_count": schedule.run_count,
        "readable": described.get("readable", schedule.cron),
        "next_in": daemon.describe_next(schedule) if schedule.enabled else "paused",
        "last_run": _humanise_delta(schedule.last_run_at),
    }


@app.get("/schedules", response_class=HTMLResponse)
def schedules_page(request: Request):
    store = get_store()
    daemon.sync_schedules()
    return templates.TemplateResponse(
        request=request,
        name="schedules.html",
        context=_context(
            request,
            "schedules",
            schedules=[_schedule_view(s, store) for s in store.list_schedules(None)],
        ),
    )


@app.post("/schedules/{schedule_id}/toggle", response_class=HTMLResponse)
def schedule_toggle(request: Request, schedule_id: str):
    store = get_store()
    schedule = store.schedules.get("schedule_id", schedule_id)
    if schedule is None:
        raise HTTPException(404, "No such schedule")
    schedule.enabled = not schedule.enabled
    schedule.next_run_at = (
        daemon.next_fire(schedule.cron, schedule.timezone) if schedule.enabled else None
    )
    store.schedules.put(schedule, "schedule_id")
    return templates.TemplateResponse(
        request=request, name="_schedule_row.html", context={"s": _schedule_view(schedule, store)}
    )


@app.post("/schedules/{schedule_id}/run", response_class=HTMLResponse)
def schedule_run_now(request: Request, schedule_id: str):
    store = get_store()
    schedule = store.schedules.get("schedule_id", schedule_id)
    if schedule is None:
        raise HTTPException(404, "No such schedule")
    try:
        _run_in_background(schedule.workflow_id)
    except KeyError:
        raise HTTPException(404, "That workflow no longer exists") from None
    return templates.TemplateResponse(
        request=request, name="_schedule_row.html", context={"s": _schedule_view(schedule, store)}
    )


# --- credentials ------------------------------------------------------------


def _credentials_page(request: Request, flash: str = "", kind: str = "ok"):
    return templates.TemplateResponse(
        request=request,
        name="credentials.html",
        context=_context(
            request,
            "credentials",
            credentials=creds.catalogue(None),
            flash=flash,
            flash_kind=kind,
        ),
    )


def _credentials_fragment(request: Request, flash: str = "", kind: str = "ok"):
    return templates.TemplateResponse(
        request=request,
        name="_credentials_list.html",
        context={
            "credentials": creds.catalogue(None),
            "flash": flash,
            "flash_kind": kind,
        },
    )


@app.get("/credentials", response_class=HTMLResponse)
def credentials_page(request: Request):
    return _credentials_page(request)


@app.post("/credentials/gmail/auth", response_class=HTMLResponse)
def credentials_gmail_auth(request: Request):
    """Run the Gmail MCP server's own OAuth flow — a browser popup, once.

    Blocks for the duration (the user is off approving a Google consent
    screen), which is fine here: it's a single click from a page they're
    already looking at, not a background job.
    """
    result = creds.run_gmail_auth()
    if result["ok"]:
        return _credentials_fragment(request, result["message"], "ok")
    return _credentials_fragment(request, result["error"], "bad")


@app.post("/credentials/speech/check", response_class=HTMLResponse)
def credentials_speech_check(request: Request):
    """Say one word and hear half a second of silence — a real round trip."""
    from handoff import doctor

    result = doctor.check_speech()
    flash = f"{result['name']}: {result['detail']}" + (f" — {result['fix']}" if result.get("fix") and result["status"] != "ok" else "")
    return templates.TemplateResponse(
        request=request, name="_credentials_list.html",
        context={"credentials": creds.catalogue(), "flash": flash, "flash_kind": "error" if result["status"] == "fail" else "ok"},
    )


@app.post("/credentials/connect", response_class=HTMLResponse)
def credentials_connect(
    request: Request, provider: str = Form(...), secret: str = Form("")
):
    if not secret.strip():
        return _credentials_fragment(request, "Paste a key first.", "bad")
    try:
        cred = creds.connect(provider, secret, _workspace().workspace_id)
    except KeyError:
        return _credentials_fragment(request, f"Unknown provider '{provider}'.", "bad")

    if cred.status.value == "connected":
        return _credentials_fragment(request, f"{cred.label} connected.", "ok")
    return _credentials_fragment(
        request, f"Saved, but the check failed: {cred.last_error}", "bad"
    )


@app.post("/credentials/{credential_id}/check", response_class=HTMLResponse)
def credentials_check(request: Request, credential_id: str):
    try:
        cred = creds.verify(credential_id)
    except KeyError:
        return _credentials_fragment(request, "That credential is gone.", "bad")
    ok = cred.status.value == "connected"
    return _credentials_fragment(
        request,
        f"{cred.label}: {'working' if ok else cred.last_error or 'not connected'}",
        "ok" if ok else "bad",
    )


@app.post("/credentials/{credential_id}/disconnect", response_class=HTMLResponse)
def credentials_disconnect(request: Request, credential_id: str):
    creds.disconnect(credential_id)
    return _credentials_fragment(request, "Forgotten.", "ok")


# --- tool servers -----------------------------------------------------------


def _server_view(server) -> dict[str, Any]:
    from handoff.platform import mcp_service

    return {**server.model_dump(mode="json"), "ready": mcp_service.is_ready(server)}


def _mcp_page(request: Request, server_id: str = "", section: str = "overview"):
    from handoff.platform import mcp_service

    store = get_store()
    servers = [_server_view(x) for x in store.list_mcp_servers(None)]
    selected = None
    tools = None
    used_by: list[dict[str, Any]] = []
    if server_id:
        row = store.mcp_servers.get("server_id", server_id)
        if row is None:
            raise HTTPException(404, "No such server")
        selected = _server_view(row)
        if section == "tools":
            try:
                tools = mcp_service.describe_tools(row) if mcp_service.is_ready(row) else None
            except Exception as exc:
                row.last_error = str(exc)[:200]
                store.mcp_servers.put(row, "server_id")
                selected = _server_view(row)
                tools = None
        elif section == "usage":
            used_by = mcp_service.usage_of(row)
    return templates.TemplateResponse(
        request=request,
        name="mcp.html",
        context=_context(
            request,
            "mcp",
            servers=servers,
            selected=selected,
            section=section,
            tools=tools,
            used_by=used_by,
            registry=mcp_service.registry_catalogue(),
        ),
    )


@app.get("/mcp", response_class=HTMLResponse)
def mcp_page(request: Request):
    return _mcp_page(request)


@app.get("/mcp/{server_id}", response_class=HTMLResponse)
def mcp_detail(request: Request, server_id: str):
    return _mcp_page(request, server_id, "overview")


@app.get("/mcp/{server_id}/{section}", response_class=HTMLResponse)
def mcp_section(request: Request, server_id: str, section: str):
    if section not in ("overview", "tools", "usage"):
        raise HTTPException(404, "No such section")
    return _mcp_page(request, server_id, section)


@app.post("/mcp/{server_id}/invoke", response_class=HTMLResponse)
def mcp_invoke(server_id: str, tool: str = Form(...), arguments: str = Form("{}")):
    """Call one tool on a server from the UI and show the raw result."""
    from handoff.platform import mcp_service

    row = get_store().mcp_servers.get("server_id", server_id)
    if row is None:
        raise HTTPException(404, "No such server")
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return HTMLResponse(f'<div class="callout error">Arguments are not valid JSON: {exc}</div>')
    try:
        result = mcp_service.invoke(row, tool, args)
    except Exception as exc:
        return HTMLResponse(f'<div class="callout error">{tool} failed: {str(exc)[:400]}</div>')
    body = (result.get("text") or "").replace("<", "&lt;")
    status = "error" if result.get("status") == "error" else ""
    return HTMLResponse(
        f'<div class="data {status}"><div class="data-label">{tool} · {result.get("status", "success")}</div>'
        f'<button type="button" class="button small secondary copy" data-copy>Copy</button><pre>{body}</pre></div>'
    )


@app.post("/mcp/registry/{name}/install")
def mcp_registry_install(name: str):
    from handoff.platform import mcp_service

    try:
        server = mcp_service.install_from_registry(name, _workspace().workspace_id)
    except KeyError:
        raise HTTPException(404, "Not in the registry") from None
    return RedirectResponse(f"/mcp/{server.server_id}", status_code=303)


@app.post("/mcp/save")
def mcp_save(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    transport: str = Form("stdio"),
    command: str = Form(""),
    args: str = Form(""),
    url: str = Form(""),
    required_env: str = Form(""),
):
    store = get_store()
    server = MCPServerConfig(
        workspace_id=_workspace().workspace_id,
        name=name.strip(),
        description=description,
        transport=transport,
        command=command.strip(),
        args=args.split(),
        url=url.strip(),
        required_env=required_env.split(),
    )
    store.mcp_servers.put(server, "server_id")
    return RedirectResponse(f"/mcp/{server.server_id}", status_code=303)


@app.post("/mcp/{server_id}/toggle", response_class=HTMLResponse)
def mcp_toggle(request: Request, server_id: str):
    store = get_store()
    server = store.mcp_servers.get("server_id", server_id)
    if server is not None:
        server.enabled = not server.enabled
        store.mcp_servers.put(server, "server_id")
    return _mcp_page(request, server_id, "overview")


@app.post("/mcp/{server_id}/probe", response_class=HTMLResponse)
def mcp_probe(request: Request, server_id: str):
    """Actually connect and list the tools, so 'ready' is a fact not a guess."""
    from handoff.platform import mcp_service

    server = get_store().mcp_servers.get("server_id", server_id)
    if server is None:
        raise HTTPException(404, "No such server")
    mcp_service.probe(server)
    return _mcp_page(request, server_id, "overview")


@app.post("/mcp/{server_id}/delete", response_class=HTMLResponse)
def mcp_delete(request: Request, server_id: str):
    get_store().mcp_servers.delete("server_id", server_id)
    return mcp_page(request)


# --- skills -----------------------------------------------------------------


def _skills_page(request: Request, skill_id: str = "", diff: str = ""):
    store = get_store()
    skills = store.list_skills(None)
    groups: dict[str, list] = {}
    for sk in sorted(skills, key=lambda x: (x.namespace, x.name)):
        groups.setdefault(sk.namespace, []).append(sk)
    selected = store.skills.get("skill_id", skill_id) if skill_id else None
    if skill_id and selected is None:
        raise HTTPException(404, "No such skill")
    return templates.TemplateResponse(
        request=request,
        name="skills.html",
        context=_context(
            request,
            "skills",
            skills=skills,
            groups=groups,
            selected=selected,
            markdown=skills_mod.render(selected) if selected else "",
            diff=diff,
        ),
    )


@app.get("/skills", response_class=HTMLResponse)
def skills_page(request: Request):
    return _skills_page(request)


@app.get("/skills/{skill_id}", response_class=HTMLResponse)
def skill_detail(request: Request, skill_id: str):
    return _skills_page(request, skill_id)


@app.get("/skills/{skill_id}/diff", response_class=HTMLResponse)
def skill_diff(request: Request, skill_id: str):
    skill = get_store().skills.get("skill_id", skill_id)
    if skill is None:
        raise HTTPException(404, "No such skill")
    return _skills_page(request, skill_id, diff=skills_mod.diff_with_previous(skill) or "(no changes)")


@app.post("/skills/{skill_id}/restore")
def skill_restore(skill_id: str, version: int = Form(0)):
    skill = get_store().skills.get("skill_id", skill_id)
    if skill is None or version >= len(skill.history):
        raise HTTPException(404, "No such version")
    old = skill.history[version]
    text = f"---\nname: {skill.name}\ndescription: {old.get('description', '')}\n---\n\n{old.get('body', '')}"
    skills_mod.save_from_markdown(text, skill_id=skill_id)
    return RedirectResponse(f"/skills/{skill_id}", status_code=303)


@app.post("/skills/save")
def skills_save(markdown: str = Form(...), skill_id: str = Form("")):
    skill = skills_mod.save_from_markdown(
        markdown, workspace_id=_workspace().workspace_id, skill_id=skill_id
    )
    return RedirectResponse(f"/skills/{skill.skill_id}", status_code=303)


@app.post("/skills/import")
async def skills_import(request: Request):
    form = await request.form()
    uploads = []
    for item in form.getlist("files"):
        if hasattr(item, "read"):
            uploads.append((getattr(item, "filename", "") or "", await item.read()))
    saved = skills_mod.import_files(uploads, workspace_id=_workspace().workspace_id)
    target = f"/skills/{saved[0].skill_id}" if saved else "/skills"
    response = RedirectResponse(target, status_code=303)
    response.headers["X-Toast"] = f"Imported {len(saved)} skill(s)"
    return response


@app.post("/skills/{skill_id}/toggle", response_class=HTMLResponse)
def skills_toggle(request: Request, skill_id: str):
    store = get_store()
    skill = store.skills.get("skill_id", skill_id)
    if skill is not None:
        skill.enabled = not skill.enabled
        store.skills.put(skill, "skill_id")
    return _skills_page(request, skill_id)


@app.post("/skills/{skill_id}/delete", response_class=HTMLResponse)
def skills_delete(request: Request, skill_id: str):
    get_store().skills.delete("skill_id", skill_id)
    return skills_page(request)


# --- agents -----------------------------------------------------------------


@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="agents.html",
        context=_context(
            request,
            "agents",
            agents=store.list_custom_agents(None),
            skills=[s for s in store.list_skills(None) if s.enabled],
            available_tools=agents_registry.AVAILABLE_TOOLS,
        ),
    )


@app.get("/agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(request: Request, agent_id: str):
    store = get_store()
    agent = store.custom_agents.get("agent_id", agent_id)
    if agent is None:
        raise HTTPException(404, "No such agent")

    resolved = agent.system_prompt
    block = skills_mod.compose(agent.skills, None)
    if block:
        resolved = f"{resolved}\n\n{block}".strip()

    from handoff.platform import workbench

    return templates.TemplateResponse(
        request=request,
        name="agent_detail.html",
        context=_context(
            request,
            "agents",
            agent=agent,
            skills=[s for s in store.list_skills(None) if s.enabled],
            available_tools=agents_registry.AVAILABLE_TOOLS,
            resolved_prompt=resolved or "(empty)",
            runs=store.list_agent_runs(agent_id),
            preflight=workbench.preflight(agent),
        ),
    )


@app.post("/agents/{agent_id}/run", response_class=HTMLResponse)
def agent_run(request: Request, agent_id: str, prompt: str = Form(...)):
    """Run the agent on a prompt from the workbench; returns a live card."""
    from handoff.platform import workbench

    agent = get_store().custom_agents.get("agent_id", agent_id)
    if agent is None:
        raise HTTPException(404, "No such agent")
    record = workbench.run(agent, prompt)
    return templates.TemplateResponse(
        request=request, name="agent_workbench_partial.html", context={"r": record, "request": request}
    )


@app.get("/agents/{agent_id}/runs/{run_id}", response_class=HTMLResponse)
def agent_run_card(request: Request, agent_id: str, run_id: str):
    record = get_store().agent_runs.get("run_id", run_id)
    if record is None:
        raise HTTPException(404, "No such run")
    return templates.TemplateResponse(
        request=request, name="agent_workbench_partial.html", context={"r": record, "request": request}
    )


@app.get("/agents/{agent_id}/runs/{run_id}/events")
def agent_run_events(agent_id: str, run_id: str):
    from handoff.platform import workbench

    def stream():
        for event in events.subscribe(workbench.channel(run_id), replay=True):
            kind = event.get("kind", "note")
            if kind == "keepalive":
                yield ": keepalive\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(event, default=str)}\n\n"
            if kind in ("done", "error"):
                yield "event: end\ndata: {}\n\n"
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/agents/save", response_class=HTMLResponse)
async def agents_save(request: Request):
    form = await request.form()
    store = get_store()
    agent_id = str(form.get("agent_id", ""))

    agent = store.custom_agents.get("agent_id", agent_id) if agent_id else None
    if agent is None:
        agent = CustomAgent(workspace_id=_workspace().workspace_id, name="")

    agent.name = str(form.get("name", "")).strip() or agent.name or "Untitled agent"
    agent.description = str(form.get("description", ""))
    agent.system_prompt = str(form.get("system_prompt", ""))
    agent.model_override = str(form.get("model_override", "")).strip()
    agent.tools = [str(v) for v in form.getlist("tools")]
    agent.skills = [str(v) for v in form.getlist("skills")]
    agents_registry.save(agent)
    return agents_page(request)


@app.post("/agents/{agent_id}/delete", response_class=HTMLResponse)
def agents_delete(request: Request, agent_id: str):
    get_store().custom_agents.delete("agent_id", agent_id)
    return agents_page(request)


# --- sessions ---------------------------------------------------------------


def _run_rows(store, limit: int = 40) -> list[dict[str, Any]]:
    rows = []
    for run in store.list_runs(limit=limit):
        workflow = store.get_workflow(run.workflow_id)
        session = store.get_session(run.run_id)
        duration = ""
        if run.finished_at:
            seconds = int((run.finished_at - run.started_at).total_seconds())
            duration = f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"
        rows.append(
            {
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "workflow_name": workflow.name if workflow else run.workflow_id,
                "status": run.status.value,
                "summary": run.summary,
                "started": _ago(run.started_at),
                "duration": duration,
                "auto_count": run.auto_count,
                "interrupt_count": run.interrupt_count,
                "memory_count": run.memory_count,
                "model_calls": session.model_calls if session else 0,
                "tool_calls": session.tool_calls if session else 0,
            }
        )
    return rows


@app.get("/inspector", response_class=HTMLResponse)
def inspector_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="inspector.html",
        context=_context(request, "inspector", sessions=_run_rows(get_store())),
    )


def _blocks(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive steps by graph node, the way the run actually moved."""
    blocks: list[dict[str, Any]] = []
    for step in steps:
        node = step.get("node") or "run"
        if not blocks or blocks[-1]["node"] != node:
            blocks.append(
                {"node": node, "steps": [], "duration_ms": 0, "status": "ok", "gated": False}
            )
        block = blocks[-1]
        block["steps"].append(step)
        block["duration_ms"] += int(step.get("duration_ms") or 0)
        if step.get("status") == "error":
            block["status"] = "error"
        if step.get("gated"):
            block["gated"] = True
    return blocks


def _waterfall(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Offsets for the timeline. Steps are sequential, so offsets accumulate."""
    if not steps:
        return None
    total = sum(int(s.get("duration_ms") or 0) for s in steps) or 1
    rows, cursor = [], 0
    for s in steps:
        ms = int(s.get("duration_ms") or 0)
        rows.append(
            {
                **s,
                "left": round(cursor / total * 100, 2),
                "width": max(round(ms / total * 100, 2), 0.4),
            }
        )
        cursor += ms
    ticks = [{"pct": pct, "label": f"{int(total * pct / 100)}"} for pct in (0, 25, 50, 75, 100)]
    return {"rows": rows, "total_ms": total, "ticks": ticks}


@app.get("/inspector/{run_id}", response_class=HTMLResponse)
def inspector_detail(request: Request, run_id: str):
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "No such run")

    session = store.get_session(run_id)
    steps = [
        {
            **step.model_dump(mode="json"),
            "index": index,
            "input_pretty": json.dumps(step.input, indent=2, default=str) if step.input else "",
        }
        for index, step in enumerate(session.steps if session else [], start=1)
    ]
    workflow = store.get_workflow(run.workflow_id)
    view = _run_view(run)
    view.update(
        workflow_id=run.workflow_id,
        workflow_name=workflow.name if workflow else run.workflow_id,
        started=_ago(run.started_at),
        duration=next(
            (r["duration"] for r in _run_rows(store, limit=60) if r["run_id"] == run_id), ""
        ),
    )
    records = [u for u in store.list_usage() if u.run_id == run_id]
    usage = None
    if records:
        from handoff.platform.usage import estimate_cost

        usage = {
            "tokens": sum(u.total_tokens for u in records),
            "cost": sum(estimate_cost(u.model, u.input_tokens, u.output_tokens) for u in records),
            "model": records[-1].model,
        }

    return templates.TemplateResponse(
        request=request,
        name="inspector_detail.html",
        context=_context(
            request,
            "inspector",
            run=view,
            session=session,
            steps=steps,
            blocks=_blocks(steps),
            waterfall=_waterfall(steps),
            usage=usage,
        ),
    )


# --- artifacts --------------------------------------------------------------


@app.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request):
    store = get_store()
    rows = []
    for artifact in store.list_artifacts(None):
        rows.append(
            {
                **artifact.model_dump(mode="json"),
                "preview": artifact.content[:180] + ("…" if len(artifact.content) > 180 else ""),
                "created": _ago(artifact.created_at),
                "size": artifact.size,
            }
        )
    return templates.TemplateResponse(
        request=request, name="artifacts.html", context=_context(request, "artifacts", artifacts=rows)
    )


@app.get("/artifacts/{artifact_id}", response_class=HTMLResponse)
def artifact_detail(request: Request, artifact_id: str):
    artifact = get_store().artifacts.get("artifact_id", artifact_id)
    if artifact is None:
        raise HTTPException(404, "No such artifact")
    return templates.TemplateResponse(
        request=request,
        name="artifact_detail.html",
        context=_context(
            request, "artifacts", artifact=artifact, created=_ago(artifact.created_at)
        ),
    )


@app.get("/artifacts/{artifact_id}/raw")
def artifact_raw(artifact_id: str):
    artifact = get_store().artifacts.get("artifact_id", artifact_id)
    if artifact is None:
        raise HTTPException(404, "No such artifact")
    media = {
        "json": "application/json",
        "csv": "text/csv",
        "html": "text/html",
        "markdown": "text/markdown",
    }.get(artifact.kind, "text/plain")
    return Response(content=artifact.content, media_type=f"{media}; charset=utf-8")


# --- memory -----------------------------------------------------------------


@app.get("/memory", response_class=HTMLResponse)
def memory_page(request: Request):
    store = get_store()
    rules = list_preferences()
    entries = store.memory_entries.all()
    rows = []
    for w in store.list_workspaces():
        rows.append(
            {
                "workspace_id": w.workspace_id,
                "name": w.name,
                "description": w.description,
                "color": w.color,
                "is_default": w.is_default,
                "stores": len(store.list_memory_stores(w.workspace_id)),
                "rules": len(rules) if w.is_default else 0,
                "entries": sum(1 for e in entries if e.workspace_id == w.workspace_id),
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="memory.html",
        context=_context(
            request,
            "memory",
            rows=rows,
            rules=rules,
            entries_total=len(entries),
            backend="AgentCore" if config.USE_AGENTCORE_MEMORY else "local",
        ),
    )


def _memory_ws_page(request: Request, workspace_id: str):
    store = get_store()
    workspace = _select_workspace(workspace_id)
    stores = store.list_memory_stores(workspace_id)
    entries = sorted(
        (e for e in store.memory_entries.all() if e.workspace_id == workspace_id),
        key=lambda e: e.created_at,
        reverse=True,
    )
    by_store: dict[str, int] = {}
    for e in entries:
        by_store[e.store_id] = by_store.get(e.store_id, 0) + 1
    return templates.TemplateResponse(
        request=request,
        name="memory_ws.html",
        context=_context(
            request,
            "memory",
            workspace=workspace,
            rules=list_preferences(),
            stores=stores,
            entries=entries,
            entries_by_store=by_store,
            store_names={x.store_id: x.name for x in stores},
        ),
    )


@app.post("/memory/{workspace_id}/entries")
def memory_entry_add(workspace_id: str, store_id: str = Form(""), key: str = Form(...), content: str = Form(...)):
    from handoff.platform.models import MemoryEntry

    get_store().memory_entries.put(
        MemoryEntry(store_id=store_id, workspace_id=workspace_id, key=key.strip(), content=content.strip(), source="you"),
        "entry_id",
    )
    return RedirectResponse(f"/memory/{workspace_id}", status_code=303)


@app.post("/memory/entries/{entry_id}/delete", response_class=HTMLResponse)
def memory_entry_delete(request: Request, entry_id: str):
    store = get_store()
    entry = store.memory_entries.get("entry_id", entry_id)
    if entry is not None:
        store.memory_entries.delete("entry_id", entry_id)
    return _memory_ws_page(request, entry.workspace_id if entry else _workspace().workspace_id)


@app.post("/memory/rules/{preference_id}/delete", response_class=HTMLResponse)
def memory_forget(request: Request, preference_id: str):
    get_store().preferences.delete("preference_id", preference_id)
    return memory_page(request)


# --- usage ------------------------------------------------------------------


@app.get("/usage", response_class=HTMLResponse)
def usage_page(request: Request, workspace: str = "", model: str = ""):
    from handoff.platform.usage import PRICES, bare_model_id, estimate_cost

    store = get_store()
    records = [r for r in store.list_usage(workspace or None) if not model or r.model == model]
    all_models = sorted({r.model for r in store.list_usage(None)})

    by_model: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = by_model.setdefault(r.model, {"calls": 0, "input": 0, "output": 0})
        bucket["calls"] += 1
        bucket["input"] += r.input_tokens
        bucket["output"] += r.output_tokens
    models = []
    for m, b in sorted(by_model.items(), key=lambda kv: -(kv[1]["input"] + kv[1]["output"])):
        priced = bare_model_id(m) in PRICES
        models.append(
            {
                "model": m, **b, "total": b["input"] + b["output"],
                "cost": estimate_cost(m, b["input"], b["output"]),
                "free": priced and PRICES[bare_model_id(m)] == (0.0, 0.0),
                "priced": priced,
            }
        )
    biggest = max((m["total"] for m in models), default=0) or 1
    for m in models:
        m["share"] = round(m["total"] / biggest * 100)

    by_run: dict[str, dict[str, Any]] = {}
    for r in records:
        row = by_run.setdefault(r.run_id or "—", {"calls": 0, "tokens": 0, "cost": 0.0, "model": r.model, "at": r.at})
        row["calls"] += 1
        row["tokens"] += r.total_tokens
        row["cost"] += estimate_cost(r.model, r.input_tokens, r.output_tokens)
        row["at"] = max(row["at"], r.at)
    per_run = []
    for run_id, row in sorted(by_run.items(), key=lambda kv: kv[1]["at"], reverse=True)[:60]:
        kind = "chat" if run_id.startswith("chat_") else ("agent" if run_id.startswith("arun_") else "run")
        href = f"/chat/{run_id}" if kind == "chat" else (f"/inspector/{run_id}" if kind == "run" else "/agents")
        per_run.append({**row, "label": run_id, "kind": kind, "href": href})

    total_in = sum(r.input_tokens for r in records)
    total_out = sum(r.output_tokens for r in records)
    summary = {
        "total_input": total_in, "total_output": total_out, "total_tokens": total_in + total_out,
        "total_calls": len(records), "total_cost": sum(m["cost"] for m in models),
        "runs": len(by_run), "per_run_tokens": round((total_in + total_out) / len(by_run)) if by_run else 0,
        "models": models,
    }
    return templates.TemplateResponse(
        request=request,
        name="usage.html",
        context=_context(
            request, "usage", usage=summary, per_run=per_run, all_models=all_models,
            filter_ws=workspace, filter_model=model,
        ),
    )


# --- discover ---------------------------------------------------------------


def _discover_page(request: Request, slug_name: str = ""):
    rows = marketplace.catalogue()
    selected = next((t for t in rows if t["slug"] == slug_name), None) if slug_name else None
    if slug_name and selected is None:
        raise HTTPException(404, "No such template")
    if selected is not None:
        details = []
        for wid in selected["workflows"]:
            wf = marketplace._shipped_workflow(wid)
            if wf is not None:
                details.append({"name": wf.name, "description": wf.description, "schedule": _schedule_line(wf)})
        selected = {**selected, "workflow_details": details}
    return templates.TemplateResponse(
        request=request,
        name="discover.html",
        context=_context(request, "discover", templates=rows, selected=selected),
    )


@app.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request):
    return _discover_page(request)


@app.get("/discover/{slug_name}", response_class=HTMLResponse)
def discover_detail(request: Request, slug_name: str):
    return _discover_page(request, slug_name)


@app.post("/discover/{slug_name}/install")
def discover_install(slug_name: str, workspace_id: str = Form("")):
    try:
        result = marketplace.install(slug_name, workspace_id)
    except KeyError:
        raise HTTPException(404, "No such template") from None
    daemon.sync_schedules()
    _ACTIVE_WORKSPACE["id"] = result["workspace_id"]
    response = RedirectResponse(f"/platform/{result['workspace_id']}", status_code=303)
    response.headers["X-Toast"] = f"Imported {len(result['workflows_added'])} workflow(s)"
    return response


# --- settings ---------------------------------------------------------------


def _settings_page(request: Request, flash: str = "", kind: str = "ok"):
    from handoff.platform import settings as settings_mod

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_context(request, "settings", flash=flash, flash_kind=kind, models=settings_mod.current()),
    )


@app.post("/settings/models", response_class=HTMLResponse)
async def settings_models(request: Request):
    from handoff.platform import settings as settings_mod

    form = await request.form()
    provider = str(form.get("provider", ""))
    primary = str(form.get(f"primary_{provider}", ""))
    fallback = str(form.get(f"fallback_{provider}", ""))
    try:
        result = settings_mod.save(provider, primary, fallback)
    except ValueError as exc:
        return _settings_page(request, flash=str(exc), kind="error")
    note = " Restart Handoff for the provider change to take effect." if result["restart_needed"] else ""
    return _settings_page(request, flash=f"Models saved: {result['primary']} → {result['fallback'] or 'no fallback'}.{note}")


def _speech_label() -> str:
    from handoff import speech

    st = speech.status()
    return {"aws": f"Amazon Transcribe + Polly {st['voice']} ({st['region']})", "groq": "Groq Whisper + Orpheus", "browser": "browser only"}[st["provider"]]


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _settings_page(request)


@app.post("/settings/save", response_class=HTMLResponse)
def settings_save(request: Request, confidence_threshold: float = Form(...)):
    """Change the gate's threshold for this process.

    Deliberately not written back to .env — a value you set in a file should
    not be silently rewritten by a slider. The page says as much.
    """
    config.CONFIDENCE_THRESHOLD = max(0.0, min(1.0, confidence_threshold))
    return _settings_page(
        request,
        f"Threshold set to {config.CONFIDENCE_THRESHOLD:.0%} for this session. "
        f"Set CONFIDENCE_THRESHOLD in .env to make it permanent.",
        "ok",
    )


# --- platform API -----------------------------------------------------------


@app.get("/api/scheduler")
def api_scheduler():
    return JSONResponse(daemon.get_scheduler().status())


@app.get("/api/workspaces")
def api_workspaces():
    return JSONResponse([w.model_dump(mode="json") for w in get_store().list_workspaces()])


@app.get("/api/credentials")
def api_credentials():
    """Connection states only — secrets never leave the process."""
    return JSONResponse(creds.catalogue(None))


@app.get("/api/usage")
def api_usage():
    return JSONResponse(usage_mod.summary(None))


@app.get("/api/sessions/{run_id}")
def api_session(run_id: str):
    session = get_store().get_session(run_id)
    if session is None:
        raise HTTPException(404, "No trace for that run")
    return JSONResponse(session.model_dump(mode="json"))


# --- workspace-scoped routes ----------------------------------------------------------
# The same pages, entered through a workspace. Selecting the workspace first is
# what makes the sidebar unfold the right one and the page read from it.

_SECTIONS = {
    "activity": lambda request: dashboard(request),
    "chat": lambda request: chat_entry(request),
    "agents": lambda request: agents_page(request),
    "skills": lambda request: skills_page(request),
    "workflows": lambda request: platform_page(request),
    "runs": lambda request: inspector_page(request),
    "settings": lambda request: settings_page(request),
}


@app.get("/platform/{workspace_id}/{section}", response_class=HTMLResponse)
def workspace_section(request: Request, workspace_id: str, section: str):
    _select_workspace(workspace_id)
    handler = _SECTIONS.get(section)
    if handler is None:
        raise HTTPException(404, f"No section '{section}'")
    return handler(request)


@app.get("/memory/{workspace_id}", response_class=HTMLResponse)
def workspace_memory(request: Request, workspace_id: str):
    return _memory_ws_page(request, workspace_id)
