import * as esbuild from "esbuild";
import { readFileSync, writeFileSync } from "fs";

const PRODUCTION_API_URL = "https://gridlytics-production.up.railway.app";
const DEV_API_URL = "http://127.0.0.1:8001";

const isDev = process.env.GRIDLYTICS_ENV === "development";
const apiBaseUrl = isDev ? DEV_API_URL : PRODUCTION_API_URL;

const manifest = JSON.parse(readFileSync("manifest.json", "utf-8"));
const prodHostPermissions = manifest.host_permissions.filter((p) => !p.startsWith(DEV_API_URL));
manifest.host_permissions = isDev ? [`${DEV_API_URL}/*`, ...prodHostPermissions] : prodHostPermissions;
writeFileSync("manifest.json", JSON.stringify(manifest, null, 2) + "\n");

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
