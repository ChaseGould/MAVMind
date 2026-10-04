import { memo, type ReactNode } from "react";
import { parseMarkdown, type Inline } from "../lib/markdown";

function renderInline(nodes: Inline[], keyPrefix = ""): ReactNode[] {
  return nodes.map((n, i) => {
    const key = `${keyPrefix}${i}`;
    switch (n.type) {
      case "text":
        return n.text;
      case "br":
        return <br key={key} />;
      case "code":
        return <code key={key}>{n.text}</code>;
      case "bold":
        return <strong key={key}>{renderInline(n.children, `${key}.`)}</strong>;
      case "em":
        return <em key={key}>{renderInline(n.children, `${key}.`)}</em>;
      default:
        return null;
    }
  });
}

/** Safe markdown subset: everything becomes React text nodes, never raw HTML. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  return (
    <div className="md">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "p":
            return <p key={i}>{renderInline(b.children)}</p>;
          case "h":
            return (
              <p key={i} className={`md-h md-h${Math.min(b.level, 3)}`}>
                {renderInline(b.children)}
              </p>
            );
          case "code":
            return (
              <pre key={i} className="md-code" data-lang={b.lang || undefined}>
                <code>{b.text}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={i}>
                {b.items.map((it, j) => (
                  <li key={j}>{renderInline(it)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} start={b.start}>
                {b.items.map((it, j) => (
                  <li key={j}>{renderInline(it)}</li>
                ))}
              </ol>
            );
          default:
            return null;
        }
      })}
    </div>
  );
});
