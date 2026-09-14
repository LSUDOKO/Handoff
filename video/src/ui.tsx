import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { CSSProperties, ReactNode } from "react";
import { T } from "./theme";

/** Spring a block up and in, starting at `at` frames into the scene. */
export const Rise = ({ at = 0, children, style, dy = 28 }: { at?: number; children: ReactNode; style?: CSSProperties; dy?: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - at, fps, config: { damping: 200, stiffness: 120, mass: 0.9 } });
  const o = interpolate(frame - at, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ opacity: o, transform: `translateY(${(1 - p) * dy}px)`, ...style }}>{children}</div>;
};

export const Wordmark = ({ size = 34, color = T.ink, markColor, style }: { size?: number; color?: string; markColor?: string; style?: CSSProperties }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * 0.4, ...style }}>
    <span style={{ width: size * 1.3, height: size * 1.3, borderRadius: size * 0.38, background: markColor ?? color, display: "grid", placeItems: "center" }}>
      <span style={{ width: size * 0.42, height: size * 0.42, borderRadius: 3, background: markColor ? T.ink : T.cream, transform: "rotate(45deg)" }} />
    </span>
    <span style={{ fontFamily: T.brand, fontWeight: 600, fontSize: size, letterSpacing: "-0.02em", color }}>handoff</span>
  </div>
);

export const Pill = ({ children, dark, accent }: { children: ReactNode; dark?: boolean; accent?: boolean }) => (
  <span
    style={{
      display: "inline-flex", alignItems: "center", gap: 10, height: 44, padding: "0 20px", borderRadius: 999, fontFamily: T.sans, fontSize: 19, fontWeight: 600,
      background: accent ? T.ink : dark ? "rgba(236,234,229,0.08)" : "rgba(30,30,30,0.06)",
      color: accent ? T.cream : dark ? T.chalk : T.ink,
      border: `1px solid ${accent ? "transparent" : dark ? "rgba(236,234,229,0.16)" : "rgba(30,30,30,0.16)"}`,
    }}
  >
    {children}
  </span>
);

/** A screenshot in a soft frame. */
export const Shot = ({ src, width, style, radius = 18 }: { src: string; width: number; style?: CSSProperties; radius?: number }) => (
  <img src={src} style={{ width, borderRadius: radius, boxShadow: "0 24px 70px rgba(0,0,0,0.22), 0 0 0 1px rgba(0,0,0,0.06)", display: "block", ...style }} />
);

export const Label = ({ children, dark }: { children: ReactNode; dark?: boolean }) => (
  <div style={{ fontFamily: T.mono, fontSize: 18, letterSpacing: "0.08em", textTransform: "uppercase", color: dark ? T.chalkMuted : T.muted }}>{children}</div>
);

/** A freeze terminal capture: it already carries its window and shadow. */
export const Terminal = ({ src, width, style }: { src: string; width: number; style?: CSSProperties }) => (
  <img src={src} style={{ width, display: "block", ...style }} />
);
