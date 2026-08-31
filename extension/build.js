import * as esbuild from "esbuild";

const PRODUCTION_API_URL = "https://REPLACE_WITH_RAILWAY_URL";
const DEV_API_URL = "http://127.0.0.1:8001";

const isDev = process.env.GRIDLYTICS_ENV === "development";
const apiBaseUrl = isDev ? DEV_API_URL : PRODUCTION_API_URL;

await esbuild.build({
  entryPoints: ["src/content.tsx", "src/background.ts", "src/popup.tsx"],
  bundle: true,
  outdir: ".",
  format: "iife",
  target: "chrome110",
  jsx: "automatic",
  loader: { ".css": "text" },
  define: { __API_BASE_URL__: JSON.stringify(apiBaseUrl) },
});

console.log(`Built content.js, background.js, and popup.js (API: ${apiBaseUrl})`);
