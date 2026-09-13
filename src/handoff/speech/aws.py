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
from functools import lru_cache

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


async def _stream(pcm: bytes, rate: int, language: str) -> str:
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler
    from amazon_transcribe.model import TranscriptEvent

    client = TranscribeStreamingClient(region=config.AWS_REGION)
    stream = await client.start_stream_transcription(
        language_code=language,
        media_sample_rate_hz=rate,
        media_encoding="pcm",
        enable_partial_results_stabilization=True,
        partial_results_stability="high",
    )
    finals: list[str] = []

    class Handler(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, transcript_event: TranscriptEvent) -> None:
            for result in transcript_event.transcript.results:
                if result.is_partial:
                    continue
                for alt in result.alternatives:
                    if alt.transcript:
                        finals.append(alt.transcript)

    async def send() -> None:
        for i in range(0, len(pcm), CHUNK_BYTES):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[i : i + CHUNK_BYTES])
            await asyncio.sleep(0)
        await stream.input_stream.end_stream()

    await asyncio.gather(send(), Handler(stream.output_stream).handle_events())
    return " ".join(finals).strip()


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
