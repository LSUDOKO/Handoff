# Copyright 2026 The Handoff Authors
# SPDX-License-Identifier: Apache-2.0
"""Hearing and speaking on AWS: Transcribe streaming in, Polly out.

Streaming rather than batch Transcribe because batch means an S3 bucket, a
job, and polling — ten seconds before the first word comes back. A streaming
session per utterance returns the final transcript about a second after the
last chunk is sent, and needs nothing but credentials.

Polly's neural voices are used by default; the generative engine is a
config switch away. Repeated short phrases ("Listening.", "Done.") are
cached so they cost nothing the second time.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from handoff import config

#: Transcribe's streaming API accepts up to 32 KB per event; 100 ms of 16 kHz
#: Int16 mono is 3200 bytes, which keeps the stream close to real time.
CHUNK_BYTES = 3200


def ready() -> bool:
    """True when boto3 can find credentials — the same test Bedrock uses."""
    try:
        import boto3

        return boto3.Session().get_credentials() is not None and bool(config.AWS_REGION)
    except Exception:
        return False


class LiveTranscription:
    """One open Transcribe streaming session: PCM in, text out, as it comes.

    The orb page keeps one of these per utterance, feeding microphone frames
    over a WebSocket while the person is still talking, so the caption fills
    in live and the final text is ready the moment they stop.
    """

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self._finals: list[str] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None

    @classmethod
    async def open(cls, rate: int = 16000, language: str = "en-US") -> LiveTranscription:
        from amazon_transcribe.client import TranscribeStreamingClient

        client = TranscribeStreamingClient(region=config.AWS_REGION)
        stream = await client.start_stream_transcription(
            language_code=language,
            media_sample_rate_hz=rate,
            media_encoding="pcm",
            enable_partial_results_stabilization=True,
            # "medium" settles a partial a beat sooner than "high"; the page
            # shows partials live and takes the last one if the final is slow.
            partial_results_stability="medium",
        )
        session = cls(stream)
        session._reader = asyncio.create_task(session._read())
        return session

    async def _read(self) -> None:
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        queue, finals = self._queue, self._finals

        class Handler(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, transcript_event: Any) -> None:
                for result in transcript_event.transcript.results:
                    for alt in result.alternatives:
                        if not alt.transcript:
                            continue
                        if result.is_partial:
                            await queue.put((alt.transcript, True))
                        else:
                            finals.append(alt.transcript)
                            await queue.put((alt.transcript, False))

        try:
            await Handler(self.stream.output_stream).handle_events()
        finally:
            await queue.put(None)

    async def send(self, chunk: bytes) -> None:
        await self.stream.input_stream.send_audio_event(audio_chunk=chunk)

    async def end(self) -> None:
        await self.stream.input_stream.end_stream()

    async def results(self) -> AsyncIterator[tuple[str, bool]]:
        """Yield ``(text, is_partial)`` until the stream closes."""
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    def transcript(self) -> str:
        return " ".join(self._finals).strip()

    async def close(self) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()


async def _stream(pcm: bytes, rate: int, language: str) -> str:
    session = await LiveTranscription.open(rate, language)
    try:
        for i in range(0, len(pcm), CHUNK_BYTES):
            await session.send(pcm[i : i + CHUNK_BYTES])
            await asyncio.sleep(0)
        await session.end()
        async for _ in session.results():
            pass
        return session.transcript()
    finally:
        await session.close()


def transcribe_pcm(pcm: bytes, rate: int = 16000, language: str = "en-US") -> str:
    """Speech → text for one utterance of 16-bit mono PCM."""
    if not pcm:
        return ""
    return asyncio.run(_stream(pcm, rate, language))


@lru_cache(maxsize=64)
def synthesize(text: str, voice: str, engine: str) -> bytes:
    """Text → MP3 through Polly. Cached per (text, voice, engine)."""
    import boto3

    client = boto3.Session().client("polly", region_name=config.AWS_REGION)
    response = client.synthesize_speech(
        Text=text[:2900],
        VoiceId=voice,
        Engine=engine,
        OutputFormat="mp3",
        TextType="text",
    )
    return response["AudioStream"].read()
