import { describe, expect, it } from "vitest";
import { angleDiff, headingLabel, headingTapeTicks, pitchLadder, pitchToPixels, valueTapeTicks, wrap180, wrap360 } from "./hud";

describe("angles", () => {
  it("wrap360", () => {
    expect(wrap360(0)).toBe(0);
    expect(wrap360(360)).toBe(0);
    expect(wrap360(-10)).toBe(350);
    expect(wrap360(725)).toBe(5);
    expect(Object.is(wrap360(-360), 0)).toBe(true);
  });
  it("wrap180 / angleDiff", () => {
    expect(wrap180(190)).toBe(-170);
    expect(wrap180(180)).toBe(180);
    expect(wrap180(-180)).toBe(180);
    expect(angleDiff(10, 350)).toBe(20);
    expect(angleDiff(350, 10)).toBe(-20);
  });
});

describe("pitchToPixels", () => {
  it("scales and clamps", () => {
    expect(pitchToPixels(10, 4)).toBe(40);
    expect(pitchToPixels(-5, 4)).toBe(-20);
    expect(pitchToPixels(120, 2)).toBe(180);
  });
});

describe("heading tape", () => {
  it("labels cardinals and pads numbers", () => {
    expect(headingLabel(0)).toBe("N");
    expect(headingLabel(360)).toBe("N");
    expect(headingLabel(90)).toBe("E");
    expect(headingLabel(30)).toBe("030");
  });

  it("generates ticks across north with offsets relative to heading", () => {
    const ticks = headingTapeTicks(355, 30, 2, 5, 15);
    expect(ticks.map((t) => t.deg)).toEqual([340, 345, 350, 355, 0, 5, 10]);
    expect(ticks.map((t) => t.offset)).toEqual([-30, -20, -10, 0, 10, 20, 30]);
    const north = ticks.find((t) => t.deg === 0)!;
    expect(north.major).toBe(true);
    expect(north.label).toBe("N");
    expect(ticks.find((t) => t.deg === 345)!.label).toBe("345");
    expect(ticks.find((t) => t.deg === 5)!.major).toBe(false);
  });

  it("handles fractional headings", () => {
    const ticks = headingTapeTicks(92.5, 10, 1, 5, 15);
    expect(ticks.map((t) => t.deg)).toEqual([90, 95]);
    expect(ticks[0].offset).toBeCloseTo(-2.5);
  });
});

describe("ladders and tapes", () => {
  it("pitch ladder excludes 0 and stays within +/-90", () => {
    expect(pitchLadder(0, 25)).toEqual([-20, -10, 10, 20]);
    expect(pitchLadder(85, 20)).toEqual([70, 80, 90]);
  });
  it("value tape ticks: larger values drawn higher (negative offset)", () => {
    const t = valueTapeTicks(12, 10, 5, 2);
    expect(t.map((x) => x.value)).toEqual([10, 15]);
    expect(t[0].offset).toBe(4);
    expect(t[1].offset).toBe(-6);
  });
});
