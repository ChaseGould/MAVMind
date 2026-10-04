// SVG sparkline path building with min/max-preserving downsampling.

/**
 * Reduce `values` to at most ~`maxPoints` points. Each bucket contributes its
 * min and max (in original order) so spikes survive downsampling.
 */
export function downsample(values: number[], maxPoints: number): number[] {
  const n = values.length;
  if (maxPoints < 2 || n <= maxPoints) return values.slice();
  const buckets = Math.max(1, Math.floor(maxPoints / 2));
  const size = n / buckets;
  const out: number[] = [];
  for (let b = 0; b < buckets; b++) {
    const start = Math.floor(b * size);
    const end = Math.min(n, Math.floor((b + 1) * size));
    if (end <= start) continue;
    let minI = start;
    let maxI = start;
    for (let i = start; i < end; i++) {
      if (values[i] < values[minI]) minI = i;
      if (values[i] > values[maxI]) maxI = i;
    }
    if (minI === maxI) out.push(values[minI]);
    else if (minI < maxI) out.push(values[minI], values[maxI]);
    else out.push(values[maxI], values[minI]);
  }
  return out;
}

export type SparkGeometry = { path: string; min: number; max: number; points: number };

/**
 * SVG path ("M x y L x y ...") for values scaled into width x height with
 * `pad` px inset. Non-finite values are dropped. Flat series draw a centred
 * line. Returns an empty path for no data.
 */
export function sparklinePath(values: number[], width: number, height: number, pad = 1): SparkGeometry {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return { path: "", min: NaN, max: NaN, points: 0 };
  const innerW = Math.max(1, width - 2 * pad);
  const innerH = Math.max(1, height - 2 * pad);
  const pts = downsample(finite, Math.max(2, Math.floor(innerW)));
  let min = Infinity;
  let max = -Infinity;
  for (const v of finite) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const range = max - min;
  const n = pts.length;
  const round = (x: number) => Math.round(x * 100) / 100;
  const parts: string[] = [];
  for (let i = 0; i < n; i++) {
    const x = n === 1 ? pad + innerW / 2 : pad + (i / (n - 1)) * innerW;
    const y = range === 0 ? pad + innerH / 2 : pad + (1 - (pts[i] - min) / range) * innerH;
    parts.push(`${i === 0 ? "M" : "L"}${round(x)} ${round(y)}`);
  }
  if (n === 1) {
    // A single sample: draw a short horizontal tick so it is visible.
    const y = pad + innerH / 2;
    return { path: `M${round(pad)} ${round(y)} L${round(pad + innerW)} ${round(y)}`, min, max, points: 1 };
  }
  return { path: parts.join(" "), min, max, points: n };
}
