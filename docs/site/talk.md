# Talk

The Talk page is where you speak to Handoff and watch it work on the same screen. Say what you want done; the workflow it builds, the run it starts, the tools it calls and the decision it needs all appear as they happen, and it answers out loud.

## The orb

Open **Talk** in the sidebar (the route is `/orb`). The orb sits in the top third of the page with a one-line caption under it. Its colour tells you what it is doing:

| State | Meaning |
|---|---|
| idle | Waiting. Tap to talk. |
| wake | It heard you start. |
| listening | Recording. The orb moves with your voice. |
| thinking | The model is working on what you said. |
| speaking | Playing the reply. The orb moves with the audio. |
| acting | A tool is running — a workflow being saved, a run being started. |
| needs | Amber. A decision is waiting on you. |

Amber means exactly one thing across the whole product: waiting on you.

## Three ways to talk

**Tap.** Click the orb to start listening and click again to stop. What you said appears as a transcript under the orb, then the reply streams in and is spoken.

**Hold Space.** Press and hold the space bar while you talk; release to send. This is the fastest way to answer a decision.

**Hands-free.** Turn on the *Hands-free* toggle and the orb listens on its own: the utterance ends after 1.1 seconds of silence following at least 0.6 seconds of speech, the reply is spoken, and it re-arms when the reply finishes. A conversation flows without touching anything.

Under the hood the browser records 16 kHz mono PCM through an AudioWorklet and wraps it in a WAV header, which is what the speech services want directly. There is no ffmpeg and no webm.

## What appears

Talk drives one persisted chat per workspace, titled *Voice*, on the same chat service as the typed chat — so history, tools and learned rules are shared, and a conversation started by voice continues in the browser. The spoken assistant replies in at most two short sentences and, when you ask it to set something up, does the whole job in one turn: designs the workflow, saves it as active, and if you said to run it, starts the run.

Three kinds of card mount in the work panel as events arrive:

**The workspace card** appears when a turn saves a workflow. *Signals* shows the trigger — the cron expression, its readable form, the timezone. *Jobs* says what the workflow does: which tools run, that unsure items stop for you below the confidence threshold, and where completion notifies. *Agents* lists one row per integration (marked MCP), the executor (LLM) and the notifier (SEND).

**The run graph** appears when a run starts. It is the Strands Graph drawn as it is — `trigger → executor → completer` — with a node under the executor for every tool call, each moving through QUEUED, RUNNING and DONE with its milliseconds. This is a direct picture of the SDK's graph and its hook events, not an illustration.

**The decision card** appears when the run stops to ask. It is the same card the Activity page shows, and you can answer it by voice.

## Answering by voice

Spoken decisions are matched locally, with no model round-trip. Say any of:

- *archive it*, *bin it*, *dismiss* → `archive`
- *file a ticket*, *track it*, *make an issue* → `file_ticket`
- *draft a reply*, *respond*, *write back* → `draft_reply`
- *leave it*, *skip*, *do nothing* → `skip`

The run resumes exactly where it stopped — the same run, not a new one — and your answer becomes a rule the next run applies on its own. See [The gate](/docs/the-gate).

## Speech providers

Hearing and speaking sit behind one facade with three providers, chosen by `HANDOFF_SPEECH_PROVIDER`:

```bash
HANDOFF_SPEECH_PROVIDER=auto    # aws | groq | browser, or auto
```

`auto`, the default, takes the first that is ready: **AWS** when boto3 can resolve credentials, else **Groq** when `GROQ_API_KEY` is set, else the **browser**'s own engines. Nothing goes mute over a missing credential.

### AWS: Transcribe streaming and Polly

This is what the deployment runs on. Amazon Transcribe hears you over a streaming session — one per utterance, no S3, about a second of latency — and Amazon Polly speaks the reply as MP3. Repeated short phrases are cached, so saying "done" twice costs once.

```bash
POLLY_VOICE=Matthew          # any Polly voice id
POLLY_ENGINE=neural          # neural | generative | standard
TRANSCRIBE_LANGUAGE=en-US
```

The IAM user needs `polly:SynthesizeSpeech` and `transcribe:StartStreamTranscription`. Install the `bedrock` extra for the streaming SDK: `pip install -e ".[bedrock]"`.

Cost: Transcribe streaming is $0.024 per minute heard; Polly neural is $16 per million characters spoken. A full demo rehearsal is cents.

### Groq: Whisper and Orpheus

With a Groq key and no AWS credentials, Whisper transcribes and Orpheus speaks. Orpheus needs a one-time terms acceptance in the Groq console playground; until then the reply is spoken by the browser.

```bash
GROQ_STT_MODEL=whisper-large-v3-turbo
GROQ_TTS_MODEL=canopylabs/orpheus-v1-english
GROQ_TTS_VOICE=troy
```

### Browser

The floor. The page uses the Web Speech API for both directions. Chrome has the most complete implementation.

## Check it

```bash
handoff doctor speech
```

On AWS this synthesises one word with Polly and opens one Transcribe stream fed half a second of silence — two real calls, together well under a hundredth of a cent. The Credentials page shows the same thing as a read-only *speech* row with a **Test** button.

## On the desktop

The desktop window opens on Talk once onboarding is complete, and `Ctrl+Space` starts listening from any page. If the webview refuses microphone access, the window records natively through `sounddevice` instead — install it with `pip install -e ".[voice]"` (it needs PortAudio on Linux). The reply plays through the page either way.

## From the terminal

The same facade is available without a browser: `handoff say "text"` speaks through the configured provider, `handoff listen file.wav` transcribes a recording, and `handoff talk --mic` is a push-to-talk loop with spoken replies. See the [CLI reference](/docs/cli).
