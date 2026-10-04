// Newline-delimited JSON splitting for streamed responses.
// Chunks can split anywhere, including inside a line or a multi-byte UTF-8
// character; the splitter buffers the tail until its newline arrives.

export class NdjsonSplitter {
  private buf = "";

  /** Feed a decoded text chunk; returns the complete, non-blank lines. */
  push(chunk: string): string[] {
    this.buf += chunk;
    const parts = this.buf.split("\n");
    this.buf = parts.pop() ?? "";
    return parts.map((l) => l.replace(/\r$/, "")).filter((l) => l.trim() !== "");
  }

  /** End of stream: return any trailing line without a final newline. */
  flush(): string[] {
    const rest = this.buf.replace(/\r$/, "");
    this.buf = "";
    return rest.trim() === "" ? [] : [rest];
  }
}

export type ParsedLine<T> = { ok: true; value: T } | { ok: false; line: string; error: string };

export function parseLine<T = unknown>(line: string): ParsedLine<T> {
  try {
    return { ok: true, value: JSON.parse(line) as T };
  } catch (e) {
    return { ok: false, line, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * Read an NDJSON body from a ReadableStream of bytes, yielding parsed objects.
 * Lines that are not valid JSON are yielded as ParsedLine failures so the
 * caller can surface them rather than silently dropping data.
 */
export async function* readNdjson<T = unknown>(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ParsedLine<T>> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const splitter = new NdjsonSplitter();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of splitter.push(decoder.decode(value, { stream: true }))) {
        yield parseLine<T>(line);
      }
    }
    for (const line of splitter.push(decoder.decode())) yield parseLine<T>(line);
    for (const line of splitter.flush()) yield parseLine<T>(line);
  } finally {
    reader.releaseLock();
  }
}
