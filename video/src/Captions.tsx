import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { T } from "./theme";
import type { Scene } from "./timeline";

/** The sentence being spoken, in a pill at the foot of the frame. */
export const Captions = ({ scenes, dark }: { scenes: Scene[]; dark: (id: string) => boolean }) => {
  const frame = useCurrentFrame();
  let current: { text: string; start: number; end: number; onDark: boolean } | null = null;
  for (const s of scenes) {
    for (const sentence of s.sentences) {
      const start = s.from + sentence.from;
      const end = start + sentence.frames + 8;
      if (frame >= start && frame < end) current = { text: sentence.text, start, end, onDark: dark(s.id) };
    }
  }
  if (!current) return null;
  const inOp = interpolate(frame, [current.start, current.start + 6], [0, 1], { extrapolateRight: "clamp" });
  const outOp = interpolate(frame, [current.end - 6, current.end], [1, 0], { extrapolateLeft: "clamp" });
  const y = interpolate(frame, [current.start, current.start + 8], [10, 0], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginBottom: 56, maxWidth: 1240, padding: "16px 28px", borderRadius: 18,
          background: current.onDark ? "rgba(236,234,229,0.10)" : "rgba(30,30,30,0.82)",
          color: current.onDark ? T.chalk : "#fff", fontFamily: T.sans, fontSize: 30, lineHeight: 1.35, textAlign: "center",
          opacity: Math.min(inOp, outOp), transform: `translateY(${y}px)`, backdropFilter: "blur(10px)",
          boxShadow: "0 12px 40px rgba(0,0,0,0.18)", letterSpacing: "-0.005em",
        }}
      >
        {current.text}
      </div>
    </AbsoluteFill>
  );
};
