import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { T } from "../theme";
import { Label, Rise, Shot, Terminal } from "../ui";
import type { Scene } from "../timeline";
import { CUES } from "../timeline";

const at = (scene: Scene, i: number) => scene.sentences[Math.min(i, scene.sentences.length - 1)].from;

/** The decision: a still of the real card, the reasoning quoted, the gauge — then the live answer follows in Film. */
export const DecisionStill = ({ scene }: { scene: Scene }) => {
  const frame = useCurrentFrame();
  const d = CUES.decision;
  const zoom = interpolate(frame, [0, scene.frames], [1.0, 1.08], { extrapolateRight: "clamp" });
  const pct = Math.round(d.confidence * 100), thr = Math.round(d.threshold * 100);
  const gaugeP = interpolate(frame - at(scene, 2), [0, 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 1160, height: 1080, overflow: "hidden" }}>
        <Img src={staticFile("stills/decision.png")} style={{ width: 1920, height: 1080, transform: `translateX(-300px) scale(${zoom * 1.12})`, transformOrigin: "960px 540px", filter: "saturate(0.98)" }} />
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent 70%, #F5F3EE 100%)" }} />
      </div>
      <div style={{ position: "absolute", left: 1120, top: 150, width: 700 }}>
        <Rise at={4}><Label>Why it stopped</Label></Rise>
        <Rise at={at(scene, 1)} dy={24}>
          <div style={{ marginTop: 18, fontSize: 30, lineHeight: 1.42, color: T.ink, borderLeft: `4px solid ${T.amber}`, paddingLeft: 22, fontStyle: "italic" }}>“{d.reasoning}”</div>
        </Rise>
        <Rise at={at(scene, 2)} dy={24} style={{ marginTop: 44 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
            <span style={{ fontSize: 96, fontWeight: 500, letterSpacing: "-0.03em", color: T.amber }}>{pct}%</span>
            <span style={{ fontSize: 28, color: T.muted }}>sure · needs <b style={{ color: T.ink }}>{thr}%</b> to act alone</span>
          </div>
          <div style={{ position: "relative", height: 14, borderRadius: 99, background: "rgba(30,30,30,0.08)", marginTop: 18, overflow: "visible" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct * gaugeP}%`, borderRadius: 99, background: T.amber }} />
            <div style={{ position: "absolute", left: `${thr}%`, top: -8, width: 3, height: 30, background: T.ink, borderRadius: 2 }} />
            <div style={{ position: "absolute", left: `${thr}%`, top: 34, transform: "translateX(-50%)", fontFamily: T.mono, fontSize: 16, color: T.muted }}>threshold</div>
          </div>
        </Rise>
        <Rise at={at(scene, 2) + 30} style={{ marginTop: 70, fontSize: 30, color: T.muted }}>That gap is the product.</Rise>
      </div>
    </AbsoluteFill>
  );
};

export const RuleCard = ({ from }: { from: number }) => {
  const r = CUES.rule;
  return (
    <Rise at={from} dy={40} style={{ position: "absolute", left: 300, top: 120, width: 640 }}>
      <div style={{ background: "rgba(30,30,30,0.9)", color: T.chalk, borderRadius: 22, padding: "26px 32px", boxShadow: "0 24px 60px rgba(0,0,0,0.3)" }}>
        <Label dark>Learned from that one answer</Label>
        <div style={{ marginTop: 10, fontSize: 30, lineHeight: 1.35 }}>{r.pattern}</div>
        <div style={{ marginTop: 10, fontFamily: T.mono, fontSize: 18, color: T.champagne }}>→ {r.action}{r.match ? ` · matches ${r.match}` : ""}</div>
      </div>
    </Rise>
  );
};

/** The gate: the real lines from hitl.py, the one that matters lit. */
export const Gate = ({ scene }: { scene: Scene }) => {
  const frame = useCurrentFrame();
  const lines = CUES.gate.lines as { text: string; key?: boolean }[];
  const notes = ["raises before the tool body runs — nothing has touched your mail", "unsure items are deferred; one interrupt for the whole pass", "graph state serialised — paused at 08:04, answered at 11:30, same run"];
  return (
    <AbsoluteFill style={{ background: T.charcoal, fontFamily: T.sans, color: T.chalk, padding: "90px 120px" }}>
      <Rise at={4}><Label dark>src/handoff/graph/hooks/hitl.py</Label></Rise>
      <div style={{ display: "flex", gap: 56, marginTop: 28 }}>
        <div style={{ width: 1040, background: T.charcoalCard, borderRadius: 20, padding: "30px 0", border: "1px solid rgba(236,234,229,0.08)", fontFamily: T.mono, fontSize: 23, lineHeight: 1.65 }}>
          {lines.map((l, i) => {
            const shown = interpolate(frame, [6 + i * 3, 12 + i * 3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
            const lit = l.key ? interpolate(frame - at(scene, 1), [0, 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
            return (
              <div key={i} style={{ opacity: shown, padding: "0 30px", background: `rgba(183,121,31,${0.22 * lit})`, borderLeft: `4px solid rgba(183,121,31,${lit})`, color: l.key ? T.chalk : T.chalkMuted, whiteSpace: "pre" }}>
                {l.text}
              </div>
            );
          })}
        </div>
        <div style={{ flex: 1, paddingTop: 10 }}>
          <Rise at={at(scene, 0) + 6}><div style={{ fontSize: 46, fontWeight: 500, letterSpacing: "-0.02em", lineHeight: 1.15 }}>The whole product is one line.</div></Rise>
          {notes.map((n, i) => (
            <Rise key={n} at={at(scene, i === 0 ? 1 : i === 1 ? 1 : 2) + (i === 1 ? 60 : 12)} dy={18}>
              <div style={{ marginTop: 26, display: "flex", gap: 14, alignItems: "flex-start", fontSize: 26, lineHeight: 1.4, color: T.chalkMuted }}>
                <span style={{ width: 10, height: 10, borderRadius: 99, background: T.champagne, marginTop: 12, flex: "none" }} /><span>{n}</span>
              </div>
            </Rise>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** The Excalidraw diagram, panned and zoomed to what the narration is talking about. */
/** The Excalidraw diagram, panned and zoomed to what the narration is talking about. */
export const Architecture = ({ scene }: { scene: Scene }) => {
  const frame = useCurrentFrame();
  const k = [at(scene, 0), at(scene, 1), at(scene, 2), scene.frames];
  const ease = { extrapolateRight: "clamp" as const, extrapolateLeft: "clamp" as const };
  // Whole diagram → the Agents region → Speech and AWS → whole again. The
  // image is 1920 wide (about 1.2 px per diagram unit) under a 130 px margin.
  const scale = interpolate(frame, [k[0], k[1] + 24, k[2] + 24, k[3]], [1.0, 1.5, 1.3, 1.08], ease);
  const x = interpolate(frame, [k[0], k[1] + 24, k[2] + 24, k[3]], [0, -390, -600, -80], ease);
  const y = interpolate(frame, [k[0], k[1] + 24, k[2] + 24, k[3]], [0, -472, -214, -60], ease);
  return (
    <AbsoluteFill style={{ background: "#fff", fontFamily: T.sans, color: T.ink }}>
      <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
        <Img src={staticFile("stills/architecture.png")} style={{ width: 1920, transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: "0 0", display: "block", marginTop: 130 }} />
      </div>
      <Rise at={2} style={{ position: "absolute", left: 60, top: 40, padding: "10px 18px", borderRadius: 999, background: "rgba(255,255,255,0.85)", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }}><Label>Architecture · docs/architecture.excalidraw</Label></Rise>
    </AbsoluteFill>
  );
};

export const Strands = ({ scene }: { scene: Scene }) => {
  const items = [["Graph + GraphBuilder", "trigger → executor → completer, deterministic and replayable"], ["BeforeToolCallEvent → interrupt()", "the gate; resume returns the human's answer"], ["Before/AfterInvocationEvent", "one narrator per node — the orb draws the graph from it"], ["SessionRepository", "chats persisted in DynamoDB; terminal and browser share a session"], ["MCPClient × 5", "Gmail, Linear, Slack, GitHub, web"]];
  return (
    <AbsoluteFill style={{ background: T.charcoal, fontFamily: T.sans, color: T.chalk, padding: "80px 110px" }}>
      <Rise at={4}><Label dark>Built on the Strands Agents SDK 1.55 — every import, from the code</Label></Rise>
      <div style={{ display: "flex", gap: 60, marginTop: 30, alignItems: "flex-start" }}>
        <Rise at={8} dy={30}><Terminal src={staticFile("screens/terminal/strands.png")} width={960} style={{ marginLeft: -30, marginTop: -20 }} /></Rise>
        <div style={{ flex: 1 }}>
          {items.map(([h, s], i) => (
            <Rise key={h} at={at(scene, 1) + i * 16} dy={20}>
              <div style={{ padding: "18px 0", borderBottom: "1px solid rgba(236,234,229,0.1)" }}>
                <div style={{ fontFamily: T.mono, fontSize: 24, color: T.champagne }}>{h}</div>
                <div style={{ fontSize: 22, color: T.chalkMuted, marginTop: 6 }}>{s}</div>
              </div>
            </Rise>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Aws = ({ scene }: { scene: Scene }) => {
  const cards = [["screens/aws/agentcore.png", "AgentCore Runtime · READY / Memory · ACTIVE"], ["screens/aws/scheduler-lambda.png", "EventBridge Scheduler → Lambda → Runtime · ECR"], ["screens/terminal/doctor.png", "handoff doctor — every check is a real call"]];
  const pos = [[80, 140], [560, 300], [860, 470]];
  return (
    <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink }}>
      <Rise at={4} style={{ position: "absolute", left: 90, top: 70 }}><Label>Deployed in ap-northeast-2 · captured with the AWS CLI</Label></Rise>
      {cards.map(([src, cap], i) => (
        <Rise key={src} at={at(scene, i === 0 ? 0 : i === 1 ? 1 : 2) + 6} dy={40} style={{ position: "absolute", left: pos[i][0], top: pos[i][1], width: 980 }}>
          <Terminal src={staticFile(src)} width={980} />
          <div style={{ marginLeft: 36, marginTop: -30, fontSize: 21, color: T.muted, fontFamily: T.mono }}>{cap}</div>
        </Rise>
      ))}
    </AbsoluteFill>
  );
};

export const Surfaces = ({ scene }: { scene: Scene }) => {
  const cards = [["screens/terminal/run-watch.png", "Terminal", "handoff run --watch"], ["screens/orb.png", "Desktop", "the orb, natively"], ["screens/ui/site-hero.png", "Site", "handoff-eya.pages.dev"]];
  return (
    <AbsoluteFill style={{ background: T.cream, fontFamily: T.sans, color: T.ink, padding: "70px 90px" }}>
      <Rise at={4}><Label>Three surfaces, one gate</Label></Rise>
      <div style={{ display: "flex", gap: 34, marginTop: 26, alignItems: "flex-start" }}>
        {cards.map(([src, h, s], i) => (
          <Rise key={src} at={8 + i * 12 + (i === 2 ? at(scene, 1) - 24 : 0)} dy={34} style={{ width: 566 }}>
            {i === 0 ? <Terminal src={staticFile(src)} width={566} style={{ height: 620, objectFit: "cover", objectPosition: "top" }} /> : <Shot src={staticFile(src)} width={566} radius={14} style={{ height: 620, objectFit: "cover", objectPosition: "top" }} />}
            <div style={{ marginTop: 16, fontSize: 30, fontWeight: 500 }}>{h}</div>
            <div style={{ fontFamily: T.mono, fontSize: 19, color: T.muted, marginTop: 4 }}>{s}</div>
          </Rise>
        ))}
      </div>
    </AbsoluteFill>
  );
};
