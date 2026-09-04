import { vi } from "vitest";

vi.stubGlobal("chrome", {
  runtime: { onMessage: { addListener: vi.fn() }, sendMessage: vi.fn() },
  storage: { local: { get: vi.fn(), set: vi.fn() } },
});
