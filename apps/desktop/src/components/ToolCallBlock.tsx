import { useState } from "react";
import type { ToolPart } from "../lib/chat";
import { prettyJson } from "../lib/format";

export function ToolCallBlock({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false);
  const state = part.output === null ? "running" : part.is_error ? "error" : "ok";
  return (
    <div className={`tool tool-${state}`}>
      <button className="tool-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="caret">{open ? "▾" : "▸"}</span>
        <span className="tool-icon">ƒ</span>
        <span className="tool-name">{part.name}</span>
        <span className={`tool-state tool-state-${state}`}>{state === "running" ? "running…" : state}</span>
      </button>
      {open && (
        <div className="tool-body">
          <div className="tool-label">input</div>
          <pre>{prettyJson(part.input ?? {})}</pre>
          <div className="tool-label">result</div>
          <pre className={part.is_error ? "bad" : ""}>{part.output === null ? "(waiting)" : prettyJson(part.output)}</pre>
        </div>
      )}
    </div>
  );
}
