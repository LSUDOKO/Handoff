import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { T } from "../theme";
import { Label, Pill, Rise, Wordmark } from "../ui";
import type { Scene } from "../timeline";

const at = (scene: Scene, i: number) => scene.sentences[Math.min(i, scene.sentences.length - 1)].from;

/** A breathing orb from a real capture, driven by the frame so every render is identical. */
const Orb = ({ src, size, x, y, delay = 0 }: { src: string; size: number; x: number; y: number; delay?: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200, stiffness: 60 } });
  const breathe = 1 + 0.018 * Math.sin((frame / fps) * 2.1);
  return <Img src={staticFile(src)} style={{ position: "absolute", left: x, top: y, width: size, height: size, transform: `scale(${p * breathe})`, opacity: p, clipPath: "circle(46% at 50% 50%)", filter: "drop-shadow(0 30px 60px rgba(31,95,209,0.22))" }} />;
};

export const Open = ({ scene }: { scene: Scene }) => (
  <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink }}>
    <Rise at={2} style={{ position: "absolute", left: 96, top: 72 }}><Wordmark size={36} /></Rise>
    <div style={{ position: "absolute", left: 96, top: 300 }}>
      {["Describe it.", "Hand it off.", "It runs."].map((line, i) => (
        <Rise key={line} at={8 + i * 9} dy={40}>
          <div style={{ fontSize: 132, fontWeight: 500, letterSpacing: "-0.035em", lineHeight: 1.0, color: i === 2 ? T.blue : T.ink }}>{line}</div>
        </Rise>
      ))}
      <Rise at={at(scene, 1)} style={{ marginTop: 40, maxWidth: 820 }}>
        <div style={{ fontSize: 34, lineHeight: 1.4, color: T.muted }}>A voice-first agent on the Strands Agents SDK that runs your recurring chores on AWS — and asks only when it genuinely cannot decide.</div>
      </Rise>
    </div>
    <Orb src="stills/orb-idle.png" size={560} x={1240} y={240} delay={4} />
    <Rise at={at(scene, 1) + 20} style={{ position: "absolute", right: 96, top: 76, display: "flex", gap: 12 }}>
      <Pill accent>Agents for Humans · Professional track</Pill><Pill>Strands Agents SDK</Pill><Pill>Bedrock · AgentCore · Transcribe · Polly</Pill>
    </Rise>
  </AbsoluteFill>
);

export const Problem = ({ scene }: { scene: Scene }) => {
  const frame = useCurrentFrame();
  const lines = ["Triage the inbox.", "File the real asks.", "Archive the noise."];
  const s2 = at(scene, 1), s3 = at(scene, 2), s4 = at(scene, 3);
  return (
    <AbsoluteFill style={{ background: T.charcoal, fontFamily: T.sans, color: T.chalk, padding: "0 140px", justifyContent: "center" }}>
      <Rise at={4}><Label dark>The problem</Label></Rise>
      <Rise at={10} dy={36}><div style={{ fontSize: 92, fontWeight: 500, letterSpacing: "-0.03em", lineHeight: 1.05, marginTop: 18 }}>The half hour nobody gets back.</div></Rise>
      <div style={{ display: "flex", gap: 48, marginTop: 56 }}>
        {lines.map((l, i) => (
          <Rise key={l} at={s2 + i * 12} dy={20}>
            <div style={{ fontSize: 40, fontWeight: 500, color: T.chalk, padding: "18px 28px", borderRadius: 16, background: T.charcoalCard, border: "1px solid rgba(236,234,229,0.08)" }}>{l}</div>
          </Rise>
        ))}
      </div>
      <Rise at={s3 + 6}><div style={{ fontSize: 36, color: T.chalkMuted, marginTop: 44, maxWidth: 1400, lineHeight: 1.4 }}>None of it is hard. It's just every single morning — and never worth building a tool for.</div></Rise>
      <Rise at={s4 + 10} dy={24}>
        <div style={{ marginTop: 40, fontSize: 44, fontWeight: 500, lineHeight: 1.25, maxWidth: 1500 }}>
          The fear isn't that an agent is slow. <span style={{ color: T.champagne }}>It's that it does something you never sanctioned.</span>
        </div>
      </Rise>
      <div style={{ position: "absolute", right: 140, top: 96, fontFamily: T.mono, fontSize: 22, color: T.chalkMuted, opacity: interpolate(frame, [0, 20], [0, 1]) }}>08:00 → 08:30, every day</div>
    </AbsoluteFill>
  );
};

export const Brief = ({ scene }: { scene: Scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sweep = spring({ frame: frame - 14, fps, config: { damping: 200, stiffness: 40 } });
  const s2 = at(scene, 1);
  return (
    <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink, padding: "0 160px", justifyContent: "center" }}>
      <Rise at={4}><Label>Agents for Humans · the brief</Label></Rise>
      <Rise at={8} dy={30}>
        <div style={{ position: "relative", marginTop: 26, fontSize: 68, fontWeight: 500, letterSpacing: "-0.02em", lineHeight: 1.18, maxWidth: 1560 }}>
          <span style={{ position: "relative", zIndex: 1 }}>“an agent that <span style={{ background: `linear-gradient(90deg, ${T.amberSoft} ${sweep * 100}%, transparent ${sweep * 100}%)`, borderRadius: 8, padding: "0 6px" }}>runs autonomously and only surfaces when there's a real decision to make</span>”</span>
        </div>
      </Rise>
      <Rise at={s2} dy={30}><div style={{ marginTop: 64, fontSize: 84, fontWeight: 500, letterSpacing: "-0.03em", color: T.blue }}>We built that sentence.</div></Rise>
    </AbsoluteFill>
  );
};

export const Close = ({ scene }: { scene: Scene }) => (
  <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink, alignItems: "center", justifyContent: "center", textAlign: "center" }}>
    <Rise at={2}><Wordmark size={48} /></Rise>
    <Rise at={10} dy={36}><div style={{ marginTop: 40, fontSize: 84, fontWeight: 500, letterSpacing: "-0.03em", lineHeight: 1.08, maxWidth: 1500 }}>It does the boring part.<br />And it knows <span style={{ color: T.blue }}>when to stop and ask.</span></div></Rise>
    <Rise at={at(scene, 1)} style={{ marginTop: 56, display: "flex", gap: 14 }}>
      <Pill accent>github.com/LSUDOKO/Handoff</Pill><Pill>handoff-eya.pages.dev</Pill><Pill>Apache-2.0</Pill>
    </Rise>
    <Rise at={at(scene, 1) + 24} style={{ position: "absolute", top: 56, fontSize: 17, color: T.muted, fontFamily: T.mono }}>
      Built on the Strands Agents SDK · Amazon Bedrock · AgentCore · Transcribe · Polly · Music: “Inspired” by Kevin MacLeod (incompetech.com), CC BY 4.0
    </Rise>
  </AbsoluteFill>
);
