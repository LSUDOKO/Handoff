import { AbsoluteFill, Freeze, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { Segment } from "../timeline";
import { f } from "../timeline";
import { T } from "../theme";

/** Real footage: the clip's segments in order, each played or held. A small
 *  badge says what is live. Nothing here is drawn by the film. */
export const Live = ({ file, segments, badge, children }: { file: string; segments: Segment[]; badge?: string; children?: React.ReactNode }) => {
  const src = staticFile(file);
  let cursor = 0;
  const parts = segments.map((s) => {
    const frames = f(s.kind === "play" ? (s.to - s.from) / s.rate : s.seconds);
    const part = { ...s, at: cursor, frames };
    cursor += frames;
    return part;
  });
  return (
    <AbsoluteFill style={{ background: "#FAF9F6" }}>
      {parts.map((p, i) => (
        <Sequence key={i} from={p.at} durationInFrames={p.frames} layout="none">
          {p.kind === "play" ? (
            <OffthreadVideo src={src} startFrom={f(p.from)} endAt={f(p.to)} playbackRate={p.rate} muted style={{ width: 1920, height: 1080 }} />
          ) : (
            <Freeze frame={f(p.at)}>
              <OffthreadVideo src={src} muted style={{ width: 1920, height: 1080 }} />
            </Freeze>
          )}
        </Sequence>
      ))}
      {badge ? <Badge text={badge} /> : null}
      {children}
    </AbsoluteFill>
  );
};

const Badge = ({ text }: { text: string }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [6, 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", top: 92, right: 36, display: "flex", alignItems: "center", gap: 12, padding: "10px 18px", borderRadius: 999, background: "rgba(30,30,30,0.86)", color: "#fff", fontFamily: T.mono, fontSize: 17, letterSpacing: "0.06em", opacity: o, boxShadow: "0 8px 30px rgba(0,0,0,0.25)" }}>
      <span style={{ width: 9, height: 9, borderRadius: 99, background: "#FF5A5A", boxShadow: "0 0 0 4px rgba(255,90,90,0.25)" }} />
      {text}
    </div>
  );
};
