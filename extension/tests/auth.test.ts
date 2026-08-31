import { describe, expect, it } from "vitest";
import { generateToken, sha256Hex } from "../src/auth";

describe("sha256Hex", () => {
  it("matches the known SHA-256 hash of 'hello'", async () => {
    expect(await sha256Hex("hello")).toBe(
      "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    );
  });

  it("is deterministic", async () => {
    expect(await sha256Hex("some-token")).toBe(await sha256Hex("some-token"));
  });

  it("differs for different inputs", async () => {
    expect(await sha256Hex("token-a")).not.toBe(await sha256Hex("token-b"));
  });
});

describe("generateToken", () => {
  it("produces unique values", () => {
    const tokens = new Set(Array.from({ length: 100 }, () => generateToken()));
    expect(tokens.size).toBe(100);
  });
});
