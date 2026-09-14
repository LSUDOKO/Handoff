import narration from "./data/narration.json";
import cues from "./data/cues.json";
import { FPS } from "./theme";

export type Segment = { kind: "play"; from: number; to: number; rate: number } | { kind: "hold"; at: number; seconds: number };
export type Sentence = { text: string; file: string; seconds: number; from: number; frames: number };
export type Scene = { id: string; from: number; frames: number; sentences: Sentence[]; narrationFrames: number };

const GAP = 0.32; // seconds between sentences
const TAIL = 0.8; // seconds a scene lingers after its last word

export const f = (seconds: number) => Math.round(seconds * FPS);

/** How long a clip's segments play on screen, in seconds. */
export function segmentsLength(segments: Segment[]): number {
  return segments.reduce((n, s) => n + (s.kind === "play" ? (s.to - s.from) / s.rate : s.seconds), 0);
}

/** The visual floor for scenes that carry footage; others follow the narration. */
function visualSeconds(id: string): number {
  const c = cues as any;
  if (id === "say") return segmentsLength(c.say.segments);
  if (id === "run") return segmentsLength(c.run.segments);
  if (id === "decision") return c.decision.stillSeconds + segmentsLength(c.decide.segments);
  if (id === "quieter") return segmentsLength(c.again.segments) + c.rule.holdSeconds;
  return 0;
}

export function buildTimeline(): { scenes: Scene[]; total: number } {
  let cursor = 0;
  const scenes: Scene[] = [];
  for (const scene of narration.scenes) {
    const sentences: Sentence[] = [];
    let t = 0;
    for (const s of scene.sentences) {
      sentences.push({ ...s, from: f(t), frames: f(s.seconds) });
      t += s.seconds + GAP;
    }
    const narrationSeconds = t - GAP + TAIL;
    const frames = f(Math.max(narrationSeconds, visualSeconds(scene.id)));
    scenes.push({ id: scene.id, from: cursor, frames, sentences, narrationFrames: f(narrationSeconds) });
    cursor += frames;
  }
  return { scenes, total: cursor };
}

export const CUES = cues as any;
