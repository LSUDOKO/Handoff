import { Composition, staticFile } from "remotion";
import { Film } from "./Film";
import { buildTimeline } from "./timeline";
import { FPS } from "./theme";

// The app's three fonts, served from public/fonts so the render never
// reaches the network for them.
const FONTS = `
@font-face { font-family: "Instrument Sans"; font-weight: 400 700; src: url("${staticFile("fonts/InstrumentSans.woff2")}") format("woff2"); }
@font-face { font-family: "Comfortaa"; font-weight: 600 700; src: url("${staticFile("fonts/Comfortaa.woff2")}") format("woff2"); }
@font-face { font-family: "JetBrains Mono"; font-weight: 400 500; src: url("${staticFile("fonts/JetBrainsMono.woff2")}") format("woff2"); }
`;

export const Root = () => {
  const { total } = buildTimeline();
  return (
    <>
      <style>{FONTS}</style>
      <Composition id="HandoffDemo" component={Film} durationInFrames={total} fps={FPS} width={1920} height={1080} />
    </>
  );
};
