// Display formatters. Every formatter maps null/undefined/NaN to "--".

export const NONE = "--";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Fixed-point number with optional unit suffix; null -> "--". */
export function fmtNum(v: number | null | undefined, digits = 1, unit = ""): string {
  if (!isNum(v)) return NONE;
  const s = v.toFixed(digits);
  // Avoid "-0.0"
  const clean = /^-0(\.0+)?$/.test(s) ? s.slice(1) : s;
  return unit ? `${clean} ${unit}` : clean;
}

export function fmtInt(v: number | null | undefined, unit = ""): string {
  return fmtNum(v, 0, unit);
}

/** Seconds -> "mm:ss" (or "h:mm:ss" past an hour). Negative clamps to 0. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return NONE;
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Metres -> "123 m" below 1 km, else "1.23 km". */
export function fmtDistance(m: number | null | undefined): string {
  if (!isNum(m)) return NONE;
  if (Math.abs(m) < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(2)} km`;
}

/** Age in seconds -> compact string ("0.3 s", "12 s", "4 m", "2 h"). */
export function fmtAge(s: number | null | undefined): string {
  if (!isNum(s)) return NONE;
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 120) return `${Math.round(s)} s`;
  if (s < 7200) return `${Math.round(s / 60)} m`;
  return `${Math.round(s / 3600)} h`;
}

export function fmtBool(v: boolean | null | undefined, yes = "yes", no = "no"): string {
  if (v === null || v === undefined) return NONE;
  return v ? yes : no;
}

/** Generic field value (inspector): numbers trimmed, arrays joined. */
export function fmtField(v: unknown): string {
  if (v === null || v === undefined) return NONE;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v)) return String(v);
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e7)) return v.toExponential(4);
    return String(Number(v.toPrecision(7)));
  }
  if (Array.isArray(v)) return `[${v.map((x) => fmtField(x)).join(", ")}]`;
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** Local wall-clock time "HH:MM:SS" for a unix-seconds timestamp. */
export function fmtClock(unixS: number | null | undefined): string {
  if (!isNum(unixS)) return NONE;
  const d = new Date(unixS * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Pretty-print a string as JSON when parseable; otherwise return as-is. */
export function prettyJson(raw: unknown): string {
  if (typeof raw !== "string") {
    try {
      return JSON.stringify(raw, null, 2) ?? String(raw);
    } catch {
      return String(raw);
    }
  }
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
