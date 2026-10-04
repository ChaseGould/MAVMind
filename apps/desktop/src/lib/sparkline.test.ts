import { describe, expect, it } from "vitest";
import { downsample, sparklinePath } from "./sparkline";

describe("downsample", () => {
  it("returns a copy when already small", () => {
    const v = [1, 2, 3];
    const d = downsample(v, 10);
    expect(d).toEqual(v);
    expect(d).not.toBe(v);
  });

  it("caps the number of points and preserves spikes", () => {
    const v = Array.from({ length: 1000 }, (_, i) => (i === 517 ? 100 : 0));
    const d = downsample(v, 50);
    expect(d.length).toBeLessThanOrEqual(50);
    expect(Math.max(...d)).toBe(100);
    expect(Math.min(...d)).toBe(0);
  });

  it("keeps min/max in original order within a bucket", () => {
    expect(downsample([5, 1, 9, 3], 2)).toEqual([1, 9]);
    expect(downsample([5, 9, 1, 3], 2)).toEqual([9, 1]);
  });
});

describe("sparklinePath", () => {
  it("is empty without data", () => {
    expect(sparklinePath([], 100, 20).path).toBe("");
    expect(sparklinePath([NaN], 100, 20).points).toBe(0);
  });

  it("scales into the box with padding", () => {
    const g = sparklinePath([0, 10], 102, 22, 1);
    expect(g.path).toBe("M1 21 L101 1");
    expect(g.min).toBe(0);
    expect(g.max).toBe(10);
  });

  it("draws flat series at mid height", () => {
    expect(sparklinePath([3, 3, 3], 12, 10, 1).path).toBe("M1 5 L6 5 L11 5");
  });

  it("draws a single sample as a horizontal tick", () => {
    expect(sparklinePath([7], 10, 10, 0).path).toBe("M0 5 L10 5");
  });

  it("downsamples to the pixel width", () => {
    const vals = Array.from({ length: 500 }, (_, i) => Math.sin(i / 10));
    const g = sparklinePath(vals, 60, 20, 0);
    expect(g.points).toBeLessThanOrEqual(60);
    expect(g.path.startsWith("M0 ")).toBe(true);
  });
});
