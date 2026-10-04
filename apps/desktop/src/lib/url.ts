// URL helpers for the two service base URLs.

/** Strip trailing slashes from a base URL. */
export function trimBase(base: string): string {
  return base.trim().replace(/\/+$/, "");
}

/** Join base + path with exactly one slash between them. */
export function joinUrl(base: string, path: string): string {
  const b = trimBase(base);
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

/** http(s)://host[:port][/prefix] -> ws(s)://host[:port][/prefix]{path}. */
export function toWsUrl(httpBase: string, path = "/ws"): string {
  const joined = joinUrl(httpBase, path);
  if (/^https:\/\//i.test(joined)) return joined.replace(/^https:/i, "wss:");
  if (/^http:\/\//i.test(joined)) return joined.replace(/^http:/i, "ws:");
  if (/^wss?:\/\//i.test(joined)) return joined;
  // No scheme given: assume plain ws.
  return `ws://${joined.replace(/^\/+/, "")}`;
}

/** Light validation for the settings dialog. */
export function isHttpUrl(s: string): boolean {
  try {
    const u = new URL(s.trim());
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch {
    return false;
  }
}
