import { describe, expect, it } from "vitest";
import { injuryTagClass } from "../src/injuryStatus";

describe("injuryTagClass", () => {
  it("colors Out and IR red", () => {
    expect(injuryTagClass("Out")).toBe("gl-injury gl-injury--out");
    expect(injuryTagClass("IR")).toBe("gl-injury gl-injury--out");
  });

  it("colors Questionable and Doubtful yellow", () => {
    expect(injuryTagClass("Questionable")).toBe("gl-injury gl-injury--questionable");
    expect(injuryTagClass("Doubtful")).toBe("gl-injury gl-injury--questionable");
  });

  it("is case-insensitive", () => {
    expect(injuryTagClass("out")).toBe("gl-injury gl-injury--out");
    expect(injuryTagClass("questionable")).toBe("gl-injury gl-injury--questionable");
  });

  it("falls back to the base (red) style for an unrecognized status", () => {
    expect(injuryTagClass("Something Weird")).toBe("gl-injury");
  });
});
