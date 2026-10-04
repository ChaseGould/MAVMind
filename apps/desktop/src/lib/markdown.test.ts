import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown } from "./markdown";

describe("parseInline", () => {
  it("parses bold, em and code", () => {
    expect(parseInline("a **b** `c` *d*")).toEqual([
      { type: "text", text: "a " },
      { type: "bold", children: [{ type: "text", text: "b" }] },
      { type: "text", text: " " },
      { type: "code", text: "c" },
      { type: "text", text: " " },
      { type: "em", children: [{ type: "text", text: "d" }] },
    ]);
  });

  it("does not parse markup inside code", () => {
    expect(parseInline("`**x**`")).toEqual([{ type: "code", text: "**x**" }]);
  });

  it("leaves unmatched markers literal", () => {
    expect(parseInline("2 * 3 and **open")).toEqual([{ type: "text", text: "2 * 3 and **open" }]);
    expect(parseInline("a ` b")).toEqual([{ type: "text", text: "a ` b" }]);
  });

  it("treats HTML as plain text", () => {
    expect(parseInline("<img src=x onerror=alert(1)>")).toEqual([{ type: "text", text: "<img src=x onerror=alert(1)>" }]);
  });
});

describe("parseMarkdown", () => {
  it("splits paragraphs and line breaks", () => {
    expect(parseMarkdown("one\ntwo\n\nthree")).toEqual([
      { type: "p", children: [{ type: "text", text: "one" }, { type: "br" }, { type: "text", text: "two" }] },
      { type: "p", children: [{ type: "text", text: "three" }] },
    ]);
  });

  it("parses fenced code blocks, including unterminated ones while streaming", () => {
    expect(parseMarkdown("before\n```json\n{\"a\": 1}\n```\nafter")).toEqual([
      { type: "p", children: [{ type: "text", text: "before" }] },
      { type: "code", lang: "json", text: '{"a": 1}' },
      { type: "p", children: [{ type: "text", text: "after" }] },
    ]);
    expect(parseMarkdown("```\npartial")).toEqual([{ type: "code", lang: "", text: "partial" }]);
  });

  it("parses bullet and ordered lists", () => {
    const blocks = parseMarkdown("Status:\n- **GPS**: 3D\n- battery `12.4 V`\n\n1. first\n2. second");
    expect(blocks[0].type).toBe("p");
    expect(blocks[1]).toEqual({
      type: "ul",
      items: [
        [{ type: "bold", children: [{ type: "text", text: "GPS" }] }, { type: "text", text: ": 3D" }],
        [{ type: "text", text: "battery " }, { type: "code", text: "12.4 V" }],
      ],
    });
    expect(blocks[2]).toEqual({
      type: "ol",
      start: 1,
      items: [[{ type: "text", text: "first" }], [{ type: "text", text: "second" }]],
    });
  });

  it("a bold line starting with ** is not a bullet", () => {
    expect(parseMarkdown("**Summary** ok")[0].type).toBe("p");
  });

  it("parses headings", () => {
    expect(parseMarkdown("## Mission")).toEqual([{ type: "h", level: 2, children: [{ type: "text", text: "Mission" }] }]);
  });
});
