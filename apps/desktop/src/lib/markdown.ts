// Tiny, safe markdown subset parser. Produces an AST that the <Markdown>
// component renders with React elements (never innerHTML), so arbitrary model
// output cannot inject markup.
//
// Supported: paragraphs (single newlines become line breaks), # headings,
// fenced ``` code blocks (unterminated fences run to the end, which matters
// while text is still streaming), - / * / + bullet lists, 1. ordered lists,
// **bold**, *italic*, and `inline code`.

export type Inline =
  | { type: "text"; text: string }
  | { type: "br" }
  | { type: "code"; text: string }
  | { type: "bold"; children: Inline[] }
  | { type: "em"; children: Inline[] };

export type Block =
  | { type: "p"; children: Inline[] }
  | { type: "h"; level: number; children: Inline[] }
  | { type: "code"; lang: string; text: string }
  | { type: "ul"; items: Inline[][] }
  | { type: "ol"; start: number; items: Inline[][] };

const FENCE = /^\s*```\s*([\w+-]*)\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: "p", children: parseInlineLines(para) });
      para = [];
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = FENCE.exec(line);
    if (fence) {
      flushPara();
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i++]);
      i++; // skip closing fence (or run past the end)
      blocks.push({ type: "code", lang: fence[1] ?? "", text: body.join("\n") });
      continue;
    }
    if (line.trim() === "") {
      flushPara();
      i++;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flushPara();
      blocks.push({ type: "h", level: heading[1].length, children: parseInline(heading[2].trim()) });
      i++;
      continue;
    }
    if (BULLET.test(line) && !/^\s*\*\*/.test(line)) {
      flushPara();
      const items: Inline[][] = [];
      while (i < lines.length) {
        const m = BULLET.exec(lines[i]);
        if (m && !/^\s*\*\*/.test(lines[i])) {
          items.push(parseInline(m[1]));
          i++;
        } else if (items.length && /^\s{2,}\S/.test(lines[i]) && !ORDERED.test(lines[i])) {
          // continuation line of the previous item
          items[items.length - 1].push({ type: "br" }, ...parseInline(lines[i].trim()));
          i++;
        } else break;
      }
      blocks.push({ type: "ul", items });
      continue;
    }
    const ordered = ORDERED.exec(line);
    if (ordered) {
      flushPara();
      const items: Inline[][] = [];
      const start = Number(ordered[1]);
      while (i < lines.length) {
        const m = ORDERED.exec(lines[i]);
        if (m) {
          items.push(parseInline(m[2]));
          i++;
        } else if (items.length && /^\s{2,}\S/.test(lines[i]) && !BULLET.test(lines[i])) {
          items[items.length - 1].push({ type: "br" }, ...parseInline(lines[i].trim()));
          i++;
        } else break;
      }
      blocks.push({ type: "ol", start, items });
      continue;
    }
    para.push(line);
    i++;
  }
  flushPara();
  return blocks;
}

function parseInlineLines(lines: string[]): Inline[] {
  const out: Inline[] = [];
  lines.forEach((l, idx) => {
    if (idx > 0) out.push({ type: "br" });
    out.push(...parseInline(l));
  });
  return out;
}

/** Parse inline spans: `code`, **bold**, *em*. Unmatched markers stay literal. */
export function parseInline(s: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const pushText = () => {
    if (text) {
      const last = out[out.length - 1];
      if (last && last.type === "text") last.text += text;
      else out.push({ type: "text", text });
      text = "";
    }
  };
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === "`") {
      const end = s.indexOf("`", i + 1);
      if (end > i + 1) {
        pushText();
        out.push({ type: "code", text: s.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    } else if (ch === "*" && s[i + 1] === "*") {
      const end = s.indexOf("**", i + 2);
      if (end > i + 2) {
        pushText();
        out.push({ type: "bold", children: parseInline(s.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    } else if (ch === "*" && s[i + 1] !== undefined && s[i + 1] !== " " && s[i + 1] !== "*") {
      let end = -1;
      for (let j = i + 1; j < s.length; j++) {
        if (s[j] === "*" && s[j - 1] !== " " && s[j + 1] !== "*") {
          end = j;
          break;
        }
      }
      if (end > i + 1) {
        pushText();
        out.push({ type: "em", children: parseInline(s.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    text += ch;
    i++;
  }
  pushText();
  return out;
}
