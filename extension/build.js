import * as esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["src/content.tsx", "src/background.ts", "src/popup.tsx"],
  bundle: true,
  outdir: ".",
  format: "iife",
  target: "chrome110",
  jsx: "automatic",
  loader: { ".css": "text" },
});

console.log("Built content.js, background.js, and popup.js");
