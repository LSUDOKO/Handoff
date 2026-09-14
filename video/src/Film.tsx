import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { buildTimeline, CUES, type Scene } from "./timeline";
import { Captions } from "./Captions";
import { Live } from "./scenes/Live";
import { Open, Problem, Brief, Close } from "./scenes/Text";
import { DecisionStill, RuleCard, Gate, Architecture, Strands, Aws, Surfaces } from "./scenes/Proof";
import { f } from "./timeline";

const DARK = new Set(["problem", "gate", "strands"]);

const SceneFor = ({ scene }: { scene: Scene }) => {
  switch (scene.id) {
    case "open": return <Open scene={scene} />;
    case "problem": return <Problem scene={scene} />;
    case "brief": return <Brief scene={scene} />;
    case "say": return <Live file={CUES.say.file} segments={CUES.say.segments} badge="LIVE · Amazon Transcribe · Bedrock Nova Pro" />;
    case "run": return <Live file={CUES.run.file} segments={CUES.run.segments} badge="LIVE · Strands Graph · hook events" />;
    case "decision": {
      const still = f(CUES.decision.stillSeconds);
      return (
        <AbsoluteFill>
          <Sequence from={0} durationInFrames={still} layout="none"><DecisionStill scene={{ ...scene, frames: still }} /></Sequence>
          <Sequence from={still} layout="none"><Live file={CUES.decide.file} segments={CUES.decide.segments} badge="LIVE · answered by voice" /></Sequence>
        </AbsoluteFill>
      );
    }
    case "quieter": return (
      <Live file={CUES.again.file} segments={CUES.again.segments} badge="LIVE · second run">
        <RuleCard from={scene.sentences[2].from} />
      </Live>
    );
    case "gate": return <Gate scene={scene} />;
    case "architecture": return <Architecture scene={scene} />;
    case "strands": return <Strands scene={scene} />;
    case "aws": return <Aws scene={scene} />;
    case "surfaces": return <Surfaces scene={scene} />;
    case "close": return <Close scene={scene} />;
    default: return null;
  }
};

export const Film = () => {
  const { scenes, total } = buildTimeline();
  return (
    <AbsoluteFill style={{ background: "#F5F3EE" }}>
      <Audio src={staticFile("music/inspired.mp3")} volume={0.085} loop />
      {scenes.map((s) => (
        <Sequence key={s.id} from={s.from} durationInFrames={s.frames} name={s.id} layout="none">
          <SceneFor scene={s} />
        </Sequence>
      ))}
      {scenes.flatMap((s) => s.sentences.map((sen, i) => (
        <Sequence key={`${s.id}-${i}`} from={s.from + sen.from} durationInFrames={sen.frames + 4} layout="none">
          <Audio src={staticFile(`audio/${sen.file}`)} volume={1} />
        </Sequence>
      )))}
      <Captions scenes={scenes} dark={(id) => DARK.has(id)} />
      <Sequence from={total - 24} durationInFrames={24} layout="none"><AbsoluteFill style={{ background: "#F5F3EE", opacity: 0 }} /></Sequence>
    </AbsoluteFill>
  );
};
