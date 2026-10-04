// Pure math for the VFR HUD canvas.

/** Wrap any angle to [0, 360). */
export function wrap360(deg: number): number {
  const r = deg % 360;
  return r < 0 ? r + 360 : r === 0 ? 0 : r; // normalise -0
}

/** Wrap any angle to (-180, 180]. */
export function wrap180(deg: number): number {
  const r = wrap360(deg);
  return r > 180 ? r - 360 : r;
}

/** Signed shortest difference a - b in degrees, in (-180, 180]. */
export function angleDiff(a: number, b: number): number {
  return wrap180(a - b);
}

/**
 * Vertical pixel offset of the horizon for a given pitch. Positive pitch
 * (nose up) moves the horizon down the screen, i.e. a positive offset.
 */
export function pitchToPixels(pitchDeg: number, pxPerDeg: number): number {
  const p = Math.max(-90, Math.min(90, pitchDeg));
  return p * pxPerDeg;
}

export type TapeTick = {
  /** Heading of this tick in [0, 360). */
  deg: number;
  /** Horizontal offset from the tape centre in pixels. */
  offset: number;
  major: boolean;
  /** Label for major ticks ("N", "E", "030", ...); "" for minor ticks. */
  label: string;
};

const CARDINALS: Record<number, string> = {
  0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW",
};

export function headingLabel(deg: number): string {
  const d = Math.round(wrap360(deg));
  return CARDINALS[d] ?? String(d).padStart(3, "0");
}

/**
 * Ticks for a heading tape centred on `heading`, covering +/- spanDeg/2.
 * Ticks fall on multiples of stepDeg; every majorEvery-th degree multiple is
 * major and labelled.
 */
export function headingTapeTicks(
  heading: number,
  spanDeg: number,
  pxPerDeg: number,
  stepDeg = 5,
  majorEvery = 15,
): TapeTick[] {
  const h = wrap360(heading);
  const half = spanDeg / 2;
  const first = Math.ceil((h - half) / stepDeg) * stepDeg;
  const ticks: TapeTick[] = [];
  for (let d = first; d <= h + half + 1e-9; d += stepDeg) {
    const deg = wrap360(d);
    const major = Math.round(deg) % majorEvery === 0;
    ticks.push({ deg, offset: (d - h) * pxPerDeg, major, label: major ? headingLabel(deg) : "" });
  }
  return ticks;
}

/** Pitch ladder rungs (multiples of step, excluding 0) visible within +/- rangeDeg of pitch. */
export function pitchLadder(pitchDeg: number, rangeDeg: number, step = 10): number[] {
  const out: number[] = [];
  const lo = Math.ceil((pitchDeg - rangeDeg) / step) * step;
  for (let p = lo; p <= pitchDeg + rangeDeg; p += step) {
    if (p !== 0 && p >= -90 && p <= 90) out.push(p);
  }
  return out;
}

/** Ticks for a vertical value tape (speed/altitude) centred on `value`. */
export function valueTapeTicks(
  value: number,
  span: number,
  step: number,
  pxPerUnit: number,
): { value: number; offset: number }[] {
  const out: { value: number; offset: number }[] = [];
  const first = Math.ceil((value - span / 2) / step) * step;
  for (let v = first; v <= value + span / 2 + 1e-9; v += step) {
    // Screen y grows downward, larger values are drawn higher up.
    out.push({ value: Number(v.toFixed(6)), offset: -(v - value) * pxPerUnit });
  }
  return out;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
