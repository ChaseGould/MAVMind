import { describe, expect, it } from "vitest";
import { fmtAge, fmtBool, fmtDistance, fmtDuration, fmtField, fmtInt, fmtNum, prettyJson } from "./format";

describe("formatters", () => {
  it("maps null/undefined/NaN to --", () => {
    expect(fmtNum(null)).toBe("--");
    expect(fmtNum(undefined)).toBe("--");
    expect(fmtNum(NaN)).toBe("--");
    expect(fmtInt(null)).toBe("--");
    expect(fmtDuration(null)).toBe("--");
    expect(fmtDistance(null)).toBe("--");
    expect(fmtAge(null)).toBe("--");
    expect(fmtBool(null)).toBe("--");
    expect(fmtField(null)).toBe("--");
  });

  it("fmtNum fixes digits, units and avoids -0", () => {
    expect(fmtNum(12.345, 1)).toBe("12.3");
    expect(fmtNum(12.345, 2, "V")).toBe("12.35 V");
    expect(fmtNum(-0.04, 1)).toBe("0.0");
    expect(fmtInt(99.6, "%")).toBe("100 %");
  });

  it("fmtDuration renders mm:ss and h:mm:ss", () => {
    expect(fmtDuration(0)).toBe("00:00");
    expect(fmtDuration(65.9)).toBe("01:05");
    expect(fmtDuration(3599)).toBe("59:59");
    expect(fmtDuration(3661)).toBe("1:01:01");
    expect(fmtDuration(-5)).toBe("00:00");
  });

  it("fmtDistance switches to km", () => {
    expect(fmtDistance(0)).toBe("0 m");
    expect(fmtDistance(999.4)).toBe("999 m");
    expect(fmtDistance(1234)).toBe("1.23 km");
  });

  it("fmtAge is compact", () => {
    expect(fmtAge(0.25)).toBe("0.3 s");
    expect(fmtAge(42)).toBe("42 s");
    expect(fmtAge(600)).toBe("10 m");
    expect(fmtAge(7200)).toBe("2 h");
  });

  it("fmtField handles numbers, arrays and strings", () => {
    expect(fmtField(3)).toBe("3");
    expect(fmtField(0.1 + 0.2)).toBe("0.3");
    expect(fmtField(1e-6)).toBe("1.0000e-6");
    expect(fmtField([1, 2.5])).toBe("[1, 2.5]");
    expect(fmtField("GPS")).toBe("GPS");
  });

  it("prettyJson pretty-prints parseable strings and passes through others", () => {
    expect(prettyJson('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(prettyJson("not json")).toBe("not json");
    expect(prettyJson({ b: 2 })).toBe('{\n  "b": 2\n}');
  });
});
