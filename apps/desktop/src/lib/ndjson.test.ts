import { describe, expect, it } from "vitest";
import { NdjsonSplitter, parseLine, readNdjson } from "./ndjson";

describe("NdjsonSplitter", () => {
  it("splits complete lines and buffers partial ones across chunks", () => {
    const s = new NdjsonSplitter();
    expect(s.push('{"a":1}\n{"b"')).toEqual(['{"a":1}']);
    expect(s.push(':2}\n{"c":3')).toEqual(['{"b":2}']);
    expect(s.push("}")).toEqual([]);
    expect(s.flush()).toEqual(['{"c":3}']);
    expect(s.flush()).toEqual([]);
  });

  it("handles CRLF, blank lines and many lines per chunk", () => {
    const s = new NdjsonSplitter();
    expect(s.push('{"a":1}\r\n\r\n{"b":2}\n\n{"c":3}\n')).toEqual(['{"a":1}', '{"b":2}', '{"c":3}']);
    expect(s.flush()).toEqual([]);
  });

  it("handles one character at a time", () => {
    const s = new NdjsonSplitter();
    const text = '{"type":"text_delta","text":"hi"}\n{"type":"done","stop_reason":"end_turn"}\n';
    const out: string[] = [];
    for (const ch of text) out.push(...s.push(ch));
    expect(out.map((l) => JSON.parse(l).type)).toEqual(["text_delta", "done"]);
  });
});

describe("parseLine", () => {
  it("parses JSON and reports failures", () => {
    expect(parseLine('{"x":1}')).toEqual({ ok: true, value: { x: 1 } });
    const bad = parseLine("{nope");
    expect(bad.ok).toBe(false);
  });
});

describe("readNdjson", () => {
  it("reassembles lines split across byte chunks, including inside multi-byte chars", async () => {
    const text = '{"type":"text_delta","text":"héllo °C"}\n{"type":"done","stop_reason":"end_turn"}';
    const bytes = new TextEncoder().encode(text);
    // Split in awkward places: inside the é (2 bytes) and the ° (2 bytes).
    const cuts = [5, 27, 28, 37, 38, bytes.length];
    let prev = 0;
    const chunks = cuts.map((c) => {
      const part = bytes.slice(prev, c);
      prev = c;
      return part;
    });
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        for (const c of chunks) ctrl.enqueue(c);
        ctrl.close();
      },
    });
    const out = [];
    for await (const l of readNdjson(stream)) out.push(l);
    expect(out).toEqual([
      { ok: true, value: { type: "text_delta", text: "héllo °C" } },
      { ok: true, value: { type: "done", stop_reason: "end_turn" } },
    ]);
  });
});
