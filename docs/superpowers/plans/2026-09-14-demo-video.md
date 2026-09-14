# Demo video pipeline — plan

**Goal:** a submission-ready `handoff-demo.mp4` (1080p, ~3½ min) that tells
problem → solution → live proof → architecture → AWS and Strands proof, with
professional motion, real footage of the product, and a narrated pitch-deck
cut as a second file.

**Decisions**

- **Remotion** (React) composes the main film: typographic scenes, Ken Burns
  over the real screenshots, staged reveal of the Excalidraw diagram, synced
  captions, a music bed ducked under narration.
- **Live footage is live.** Playwright launches Chromium with a fake
  microphone fed by a WAV of the spoken sentence (`--use-file-for-fake-audio-capture`),
  clicks the real orb, and records the page while Amazon Transcribe hears it,
  Bedrock Nova Pro runs the turn, the workspace card lands, the run graph
  fills in, the decision card appears, and a second clip answers it by voice.
  Event timestamps are logged so narration can be aligned to them.
- **Narration:** Amazon Polly, generative `Matthew`, synthesised per sentence
  so each caption's start time is exact (generative voices give no word marks).
- **Music:** a CC-BY Kevin MacLeod track if downloadable, else a synthesised
  ambient bed; credited on the end card and in NOTICE.
- **Deck cut:** `docs/pitch/deck.pdf` → `pdftoppm` → per-slide Polly audio from
  `script.md` → ffmpeg concat → `handoff-pitch-deck.mp4`.
- **Disk:** `/home` has ~1 GB free, so `node_modules`, recordings and renders
  live under the session scratchpad on `/tmp`; the repo gets the source
  (`video/`), the scripts (`scripts/video/`), and never the MP4s. Renders are
  handed over directly and uploaded by the user.

**Steps**

1. Record three live clips with Playwright at 1920×1080: the spoken set-up
   (fake mic → real pipeline), the spoken decision, the second run.
2. Convert clips to H.264 MP4; extract event timeline JSON.
3. Write the narration script (14 scenes), synthesise with Polly per sentence,
   write `narration.json` with timings.
4. Build the Remotion composition (`video/src/*`): scenes, captions, music.
5. Render with Playwright's Chromium as the browser executable.
6. Build the deck cut with the ffmpeg pipeline.
7. Review frames at several timestamps; fix; hand over both MP4s; commit
   the source and scripts.
