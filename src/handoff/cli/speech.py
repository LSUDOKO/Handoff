# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""`handoff say`, `listen` and `talk` — the speech facade from a terminal.

Whatever engine the facade picks (Polly, Orpheus) is what speaks here; when
it picks the browser there is no server voice, and these commands say so
rather than pretending.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from handoff.cli import _ui

#: Sample format the facade and Transcribe expect from a microphone.
RATE = 16000

_EXT = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/ogg": ".ogg"}


def register(sub: argparse._SubParsersAction) -> None:
    p_say = sub.add_parser("say", help="Speak a sentence through the configured voice")
    p_say.add_argument("text", nargs="+")
    p_say.add_argument("--out", default="", metavar="FILE", help="Write the audio here instead of playing it")
    p_say.add_argument("--voice", default="", help="Voice id (default: the configured one)")
    p_say.set_defaults(handle=handle_say, setup=False)

    p_listen = sub.add_parser("listen", help="Transcribe an audio file")
    p_listen.add_argument("file", help="A WAV (any engine) or another format Groq accepts")
    p_listen.set_defaults(handle=handle_listen, setup=False)

    p_talk = sub.add_parser("talk", help="A spoken conversation: your microphone in, the voice out")
    p_talk.add_argument("--mic", action="store_true", help="Record push-to-talk (needs sounddevice)")
    p_talk.add_argument("--voice", default="")
    p_talk.add_argument("--new", action="store_true", help="Start a fresh chat")
    p_talk.set_defaults(handle=handle_talk)


# --- playback ---------------------------------------------------------------


def player_for(mime: str) -> list[str] | None:
    """A command that plays a file of this type and exits, or ``None``."""
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    if shutil.which("afplay"):
        return ["afplay"]
    if mime == "audio/wav" and shutil.which("aplay"):
        return ["aplay", "-q"]
    return None


def play(audio: bytes, mime: str) -> bool:
    command = player_for(mime)
    if command is None:
        return False
    with tempfile.NamedTemporaryFile(suffix=_EXT.get(mime, ".bin"), delete=False) as handle:
        handle.write(audio)
        path = handle.name
    try:
        subprocess.run([*command, path], check=False)
    finally:
        Path(path).unlink(missing_ok=True)
    return True


def _no_engine(reason: str) -> None:
    if reason == "browser":
        _ui.fail("no server speech engine — add AWS credentials (Transcribe + Polly) or a Groq key")
    else:
        _ui.fail(f"speech failed: {reason}")


def speak_out(text: str, voice: str = "", out: str = "") -> int:
    from handoff import speech

    audio, mime, reason = speech.speak(text, voice or None)
    if not audio:
        if _ui.json_mode():
            _ui.print_json({"ok": False, "error": reason})
        else:
            _no_engine(reason)
        return 1
    if out:
        Path(out).write_bytes(audio)
        if _ui.json_mode():
            _ui.print_json({"ok": True, "wrote": out, "bytes": len(audio), "mime": mime})
        else:
            _ui.ok(f"wrote {out} ({len(audio):,} bytes, {mime})")
        return 0
    if play(audio, mime):
        if _ui.json_mode():
            _ui.print_json({"ok": True, "played": True, "bytes": len(audio), "mime": mime})
        return 0
    fallback = f"handoff-say{_EXT.get(mime, '.bin')}"
    Path(fallback).write_bytes(audio)
    if _ui.json_mode():
        _ui.print_json({"ok": True, "played": False, "wrote": fallback, "mime": mime})
    else:
        _ui.warn(f"no player found (ffplay, afplay, aplay) — wrote {fallback}")
    return 0


# --- commands ---------------------------------------------------------------


def handle_say(args: argparse.Namespace) -> int:
    return speak_out(" ".join(args.text), args.voice, args.out)


def handle_listen(args: argparse.Namespace) -> int:
    from handoff import speech

    path = Path(args.file)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {args.file}")
    result = speech.transcribe(path.read_bytes(), path.name)
    if _ui.json_mode():
        _ui.print_json(result)
        return 0 if result.get("text") else 1
    if result.get("error"):
        _no_engine(result["error"])
        return 1
    _ui.console.print(result["text"], soft_wrap=True, markup=False)
    return 0


def record_push_to_talk() -> bytes:
    """Hold the line open between two Enter presses; return a WAV.

    ``RawInputStream`` hands back int16 frames as bytes, so no numpy is
    needed to build the file Transcribe wants.
    """
    import sounddevice as sd

    from handoff.speech import wav

    chunks: list[bytes] = []

    def on_audio(indata, frames, time_info, status) -> None:
        chunks.append(bytes(indata))

    input("  Enter to start recording…")
    with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", callback=on_audio):
        input("  recording — Enter to stop")
    return wav.pcm_to_wav(b"".join(chunks), RATE, 1)


def handle_talk(args: argparse.Namespace) -> int:
    from rich.prompt import Prompt

    from handoff import speech
    from handoff.chat import get_chat_service
    from handoff.cli.chat import stream_turn

    status = speech.status()
    mic = bool(args.mic)
    if mic:
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:
            _ui.warn(f"microphone unavailable ({exc}); typing in, speaking out")
            mic = False
    if mic and not status["stt"]:
        _ui.warn("no server engine to transcribe with; typing in instead")
        mic = False
    if not status["tts"]:
        _ui.warn("no server voice — replies will be text only")

    svc = get_chat_service()
    workspace = _ui.workspace()
    chat = (None if args.new else svc.latest(workspace)) or svc.create(workspace, "Voice")
    _ui.dim(f"talking on chat {chat.chat_id} — {status['provider']} speech; /quit to leave")

    warned_player = False
    while True:
        try:
            if mic:
                heard = speech.transcribe(record_push_to_talk(), "speech.wav")
                if heard.get("error"):
                    _no_engine(heard["error"])
                    return 1
                text = heard.get("text", "").strip()
                if not text:
                    _ui.dim("didn't catch that")
                    continue
                _ui.console.print(f"[bold]you[/]: {_ui.escape(text)}")
            else:
                text = Prompt.ask("[bold]you[/]", console=_ui.console).strip()
        except (EOFError, KeyboardInterrupt):
            _ui.console.print()
            return 0
        if not text:
            continue
        if text.lower() in ("/quit", "/exit", "/q", "goodbye"):
            return 0

        final = stream_turn(f"chat:{chat.chat_id}", lambda t=text: svc.send(chat.chat_id, t))
        reply = str(final.get("text", "")).strip()
        if final.get("kind") == "error" or not reply or not status["tts"]:
            continue
        audio, mime, reason = speech.speak(reply, args.voice or None)
        if not audio:
            _ui.dim(f"(voice unavailable: {reason})")
            continue
        if not play(audio, mime) and not warned_player:
            _ui.warn("no audio player found (ffplay, afplay, aplay); replies stay on screen")
            warned_player = True
