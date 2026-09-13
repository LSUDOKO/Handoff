# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Handoff's web surface: the log, the builder chat, and the decision screen.

FastAPI + HTMX + Jinja2, deliberately: no build step, no node_modules, no
bundler. `uvicorn handoff.web.server:app` and it runs.

The decision screen is the one that matters. Everything else is reporting.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

UI_DIR = Path(__file__).resolve().parent

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
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
    workspace = _workspace()
    return {
        "request": request,
        "page": page,
        "settings": config.settings_summary(),
        "workspace": workspace,
        "workspaces": store.list_workspaces(),
        "stats": store.stats(),
        "scheduler": daemon.get_scheduler().status(),
        "voice_enabled": stt_available(),
        **extra,
    }


def _decision_context(request: Request, payload: InterruptPayload) -> dict[str, Any]:
    threshold = config.CONFIDENCE_THRESHOLD
    workflow = get_store().get_workflow(payload.workflow_id)
    if workflow is not None and workflow.confidence_threshold:
        threshold = workflow.confidence_threshold

    confidence = payload.agent_analysis.confidence
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
    daemon.get_scheduler().start()
    print("[handoff] scheduler running")


@app.on_event("shutdown")
def _shutdown() -> None:
    daemon.get_scheduler().stop()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """The log: what ran, what it did, and what it needs from you."""
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_context(
            request,
            "activity",
            pending=store.pending_interrupts(),
            workflows=[_flow_view(w, store) for w in store.list_workflows()],
            audit=[_audit_view(e) for e in store.list_audit(limit=40)],
            rules=list_preferences(),
        ),
    )


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


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    """Describe a chore; get a workflow back."""
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=_context(
            request,
            "chat",
            templates_list=[
                {"workflow_id": w.workflow_id, "name": w.name, "description": w.description,
                 "tools": w.mcp_tools, "schedule": _schedule_line(w)}
                for w in load_example_workflows()
            ],
            voice_enabled=stt_available(),
        ),
    )


@app.post("/chat/send", response_class=HTMLResponse)
def chat_send(request: Request, message: str = Form(...)):
    """One turn with the Builder Agent."""
    session_id = request.cookies.get("handoff_session", "default")
    session = _SESSIONS.setdefault(session_id, BuilderSession())

    try:
        result = session.send(message)
        reply, cfg = result["reply"], result["config"]
    except Exception as exc:
        reply, cfg = (
            f"I couldn't reach the model just now: {exc}\n\n"
            "Check your AWS credentials and Bedrock model access, or set "
            "HANDOFF_FAKE_MODEL=true to try the flow offline.",
            None,
        )

    config_json = json.dumps(cfg, indent=2) if cfg else ""
    response = templates.TemplateResponse(
        request=request,
        name="_chat_turns.html",
        context={
            "user_message": message,
            "reply": reply,
            "config_json": config_json,
            "config_json_attr": json.dumps(config_json) if cfg else "null",
        },
    )
    response.set_cookie("handoff_session", session_id, httponly=True, samesite="lax")
    return response


@app.post("/chat/save", response_class=HTMLResponse)
def chat_save(request: Request, config: str = Form(...)):
    """Save the config the Builder just produced."""
    from handoff.models import WorkflowConfig, WorkflowStatus

    try:
        parsed = json.loads(config)
    except json.JSONDecodeError as exc:
        return HTMLResponse(f'<div class="turn"><div class="body">That config is not valid JSON: {exc}</div></div>')

    result = validate_config_dict(parsed)
    if not result["valid"]:
        problems = "\n".join(f"- {e}" for e in result["errors"])
        return HTMLResponse(
            f'<div class="turn"><p class="speaker">Handoff</p><div class="body">'
            f"I can't save that yet:\n{problems}</div></div>"
        )

    workflow = WorkflowConfig.model_validate(result["config"])
    workflow.status = WorkflowStatus.ACTIVE
    get_store().save_workflow(workflow)

    return HTMLResponse(
        f'<div class="turn"><p class="speaker">Handoff</p><div class="body">'
        f'Saved <strong>{workflow.name}</strong> and switched it on. '
        f'<a href="/">See it in the log</a> — or press Run now to watch it go.'
        f"</div></div>"
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


# --- voice ---------------------------------------------------------------------


@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: Annotated[UploadFile, File()]):
    """Speech → text through Groq Whisper. The browser records; we transcribe."""
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty recording")
    result = transcribe(data, filename=audio.filename or "speech.webm")
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return JSONResponse(result)


@app.post("/api/voice/speak")
def voice_speak(body: dict):
    """Text → speech through Groq Orpheus. 204 means: use the browser's voice."""
    audio, reason = speak(str(body.get("text", "")))
    if audio is None:
        return Response(status_code=204, headers={"X-Handoff-Fallback": reason})
    return Response(content=audio, media_type="audio/wav")


@app.post("/api/voice/command")
def voice_command(body: dict):
    """Map a spoken phrase to a decision action, without a model round-trip."""
    action = parse_command(str(body.get("text", "")), body.get("options"))
    return JSONResponse({"action": action, "heard": body.get("text", "")})


@app.get("/api/voice/status")
def voice_status():
    return JSONResponse({"stt": stt_available(), "tts_model": config.GROQ_TTS_MODEL})


# --- templates -------------------------------------------------------------------


@app.post("/chat/template/{workflow_id}", response_class=HTMLResponse)
def chat_from_template(request: Request, workflow_id: str):
    """Start the builder from one of the shipped templates."""
    workflow = next((w for w in load_example_workflows() if w.workflow_id == workflow_id), None)
    if workflow is None:
        raise HTTPException(404, "No such template")
    cfg = workflow.model_dump(mode="json", exclude={"created_at", "updated_at", "status"})
    config_json = json.dumps(cfg, indent=2)
    return templates.TemplateResponse(
        request=request,
        name="_chat_turns.html",
        context={
            "user_message": f"Start from the {workflow.name} template",
            "reply": (
                f"Here's {workflow.name}. It runs {_schedule_line(workflow)} and uses "
                f"{', '.join(workflow.mcp_tools)}.\n\n{workflow.description}\n\n"
                "Tell me what to change — the schedule, the channel, what counts as "
                "urgent — or save it as is."
            ),
            "config_json": config_json,
            "config_json_attr": json.dumps(config_json),
        },
    )


# --- machine-readable endpoints (for scripts and external callers) --------


@app.get("/api/pending")
def api_pending():
    return JSONResponse(
        [p.model_dump(mode="json") for p in get_store().pending_interrupts()]
    )


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
    return {"ok": True, "settings": config.settings_summary()}


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
):
    from handoff.platform.bootstrap import seed_memory_stores

    store = get_store()
    workspace = Workspace(name=name.strip(), description=description, icon=icon or "◆")
    store.workspaces.put(workspace, "workspace_id")
    seed_memory_stores(workspace.workspace_id)
    _ACTIVE_WORKSPACE["id"] = workspace.workspace_id
    return _settings_page(request, flash=f"Created {workspace.name}.", kind="ok")


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


# --- workflows --------------------------------------------------------------


@app.get("/platform", response_class=HTMLResponse)
def platform_page(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="platform.html",
        context=_context(
            request,
            "platform",
            workflows=[_flow_view(w, store) for w in store.list_workflows()],
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
    ready = all(os.getenv(var) for var in server.required_env) if server.required_env else True
    return {**server.model_dump(mode="json"), "ready": ready}


@app.get("/mcp", response_class=HTMLResponse)
def mcp_page(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="mcp.html",
        context=_context(
            request, "mcp", servers=[_server_view(s) for s in store.list_mcp_servers(None)]
        ),
    )


@app.post("/mcp/save", response_class=HTMLResponse)
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
    return mcp_page(request)


@app.post("/mcp/{server_id}/toggle", response_class=HTMLResponse)
def mcp_toggle(request: Request, server_id: str):
    store = get_store()
    server = store.mcp_servers.get("server_id", server_id)
    if server is not None:
        server.enabled = not server.enabled
        store.mcp_servers.put(server, "server_id")
    return mcp_page(request)


@app.post("/mcp/{server_id}/probe", response_class=HTMLResponse)
def mcp_probe(request: Request, server_id: str):
    """Actually connect and list the tools, so 'ready' is a fact not a guess."""
    store = get_store()
    server = store.mcp_servers.get("server_id", server_id)
    if server is None:
        raise HTTPException(404, "No such server")

    from handoff.mcp.servers import get_client

    try:
        client = get_client(server.name)
        server.tool_names = [t.tool_name for t in client.list_tools_sync()]
        server.last_error = ""
    except Exception as exc:
        server.last_error = str(exc)[:200]
    store.mcp_servers.put(server, "server_id")
    return mcp_page(request)


@app.post("/mcp/{server_id}/delete", response_class=HTMLResponse)
def mcp_delete(request: Request, server_id: str):
    get_store().mcp_servers.delete("server_id", server_id)
    return mcp_page(request)


# --- skills -----------------------------------------------------------------


@app.get("/skills", response_class=HTMLResponse)
def skills_page(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request=request,
        name="skills.html",
        context=_context(request, "skills", skills=store.list_skills(None)),
    )


@app.get("/skills/{skill_id}", response_class=HTMLResponse)
def skill_detail(request: Request, skill_id: str):
    store = get_store()
    skill = store.skills.get("skill_id", skill_id)
    if skill is None:
        raise HTTPException(404, "No such skill")
    return templates.TemplateResponse(
        request=request,
        name="skill_detail.html",
        context=_context(request, "skills", skill=skill, markdown=skills_mod.render(skill)),
    )


@app.post("/skills/save", response_class=HTMLResponse)
def skills_save(request: Request, markdown: str = Form(...), skill_id: str = Form("")):
    skills_mod.save_from_markdown(
        markdown, workspace_id=_workspace().workspace_id, skill_id=skill_id
    )
    return skills_page(request)


@app.post("/skills/{skill_id}/toggle", response_class=HTMLResponse)
def skills_toggle(request: Request, skill_id: str):
    store = get_store()
    skill = store.skills.get("skill_id", skill_id)
    if skill is not None:
        skill.enabled = not skill.enabled
        store.skills.put(skill, "skill_id")
    return skills_page(request)


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
        ),
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


@app.get("/inspector", response_class=HTMLResponse)
def inspector_page(request: Request):
    store = get_store()
    rows = []
    for run in store.list_runs(limit=40):
        workflow = store.get_workflow(run.workflow_id)
        session = store.get_session(run.run_id)
        duration = ""
        if run.finished_at:
            seconds = int((run.finished_at - run.started_at).total_seconds())
            duration = f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"
        rows.append(
            {
                "run_id": run.run_id,
                "workflow_name": workflow.name if workflow else run.workflow_id,
                "status": run.status.value,
                "summary": run.summary,
                "started": _ago(run.started_at),
                "duration": duration,
                "model_calls": session.model_calls if session else 0,
                "tool_calls": session.tool_calls if session else 0,
            }
        )
    return templates.TemplateResponse(
        request=request, name="inspector.html", context=_context(request, "inspector", sessions=rows)
    )


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
            "input_pretty": json.dumps(step.input, indent=2, default=str) if step.input else "",
        }
        for step in (session.steps if session else [])
    ]

    return templates.TemplateResponse(
        request=request,
        name="inspector_detail.html",
        context=_context(
            request,
            "inspector",
            run=_run_view(run),
            session=session,
            steps=steps,
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
    return templates.TemplateResponse(
        request=request,
        name="memory.html",
        context=_context(
            request,
            "memory",
            rules=list_preferences(),
            stores=store.list_memory_stores(None),
            backend="AgentCore" if config.USE_AGENTCORE_MEMORY else "local",
        ),
    )


@app.post("/memory/rules/{preference_id}/delete", response_class=HTMLResponse)
def memory_forget(request: Request, preference_id: str):
    get_store().preferences.delete("preference_id", preference_id)
    return memory_page(request)


# --- usage ------------------------------------------------------------------


@app.get("/usage", response_class=HTMLResponse)
def usage_page(request: Request):
    summary = usage_mod.summary(None)
    biggest = max((m["total"] for m in summary["models"]), default=0) or 1
    for model in summary["models"]:
        model["share"] = round(model["total"] / biggest * 100)
    return templates.TemplateResponse(
        request=request, name="usage.html", context=_context(request, "usage", usage=summary)
    )


# --- discover ---------------------------------------------------------------


@app.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="discover.html",
        context=_context(request, "discover", templates=marketplace.catalogue()),
    )


@app.post("/discover/{slug}/install", response_class=HTMLResponse)
def discover_install(request: Request, slug: str):
    try:
        marketplace.install(slug, _workspace().workspace_id)
    except KeyError:
        raise HTTPException(404, "No such template") from None
    daemon.sync_schedules()
    return discover_page(request)


# --- settings ---------------------------------------------------------------


def _settings_page(request: Request, flash: str = "", kind: str = "ok"):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_context(request, "settings", flash=flash, flash_kind=kind),
    )


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
