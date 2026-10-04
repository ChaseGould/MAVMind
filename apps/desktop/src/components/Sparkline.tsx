import { sparklinePath } from "../lib/sparkline";

export function Sparkline({ values, width = 160, height = 32 }: { values: number[]; width?: number; height?: number }) {
  const g = sparklinePath(values, width, height, 2);
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {g.path && <path d={g.path} fill="none" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}
