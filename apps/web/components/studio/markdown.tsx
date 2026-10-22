"use client";

import { cn } from "@messer/ui";
import * as React from "react";

import { type Block, type Inline, parseMarkdown } from "@/lib/studio/markdown";

function renderInline(nodes: Inline[], keyPrefix = "i"): React.ReactNode[] {
  return nodes.map((node, idx) => {
    const key = `${keyPrefix}-${idx}`;
    switch (node.t) {
      case "text":
        return <React.Fragment key={key}>{node.v}</React.Fragment>;
      case "code":
        return (
          <code key={key} className="rounded-sm border border-border bg-subtle px-1 py-px font-mono text-[0.85em]">
            {node.v}
          </code>
        );
      case "strong":
        return (
          <strong key={key} className="font-semibold">
            {renderInline(node.c, key)}
          </strong>
        );
      case "em":
        return <em key={key}>{renderInline(node.c, key)}</em>;
      case "del":
        return <del key={key}>{renderInline(node.c, key)}</del>;
      case "link": {
        const external = /^(https?:|mailto:)/i.test(node.href);
        return (
          <a
            key={key}
            href={node.href}
            className="text-accent underline underline-offset-2 hover:no-underline"
            {...(external ? { target: "_blank", rel: "noopener noreferrer nofollow" } : {})}
          >
            {renderInline(node.c, key)}
          </a>
        );
      }
      case "br":
        return <br key={key} />;
      default:
        return null;
    }
  });
}

function renderBlocks(blocks: Block[], keyPrefix = "b", tight = false): React.ReactNode[] {
  return blocks.map((block, idx) => {
    const key = `${keyPrefix}-${idx}`;
    switch (block.t) {
      case "p":
        return tight ? (
          <React.Fragment key={key}>{renderInline(block.c, key)}</React.Fragment>
        ) : (
          <p key={key}>{renderInline(block.c, key)}</p>
        );
      case "h": {
        const size = block.level <= 2 ? "text-md" : "text-base";
        const Tag = `h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6";
        return (
          <Tag key={key} className={cn("font-semibold", size)}>
            {renderInline(block.c, key)}
          </Tag>
        );
      }
      case "code":
        return (
          <div key={key} className="overflow-hidden rounded-md border border-border bg-subtle">
            {block.lang ? (
              <div className="border-b border-border px-3 py-1 font-mono text-[11px] text-fg-subtle">{block.lang}</div>
            ) : null}
            <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed">
              <code>{block.v.replace(/\n+$/, "")}</code>
            </pre>
          </div>
        );
      case "quote":
        return (
          <blockquote key={key} className="flex flex-col gap-2 border-l-2 border-border-strong pl-3 text-fg-muted">
            {renderBlocks(block.c, key)}
          </blockquote>
        );
      case "list": {
        const items = block.items.map((item, i) => {
          const single = item.length === 1 && item[0]?.t === "p";
          return (
            <li key={`${key}-${i}`} className="pl-1">
              {single ? renderBlocks(item, `${key}-${i}`, true) : <div className="flex flex-col gap-1.5">{renderBlocks(item, `${key}-${i}`)}</div>}
            </li>
          );
        });
        return block.ordered ? (
          <ol key={key} start={block.start} className="flex list-decimal flex-col gap-1 pl-5">
            {items}
          </ol>
        ) : (
          <ul key={key} className="flex list-disc flex-col gap-1 pl-5">
            {items}
          </ul>
        );
      }
      case "hr":
        return <hr key={key} className="border-border" />;
      case "table":
        return (
          <div key={key} className="overflow-x-auto rounded-md border border-border">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-subtle">
                <tr>
                  {block.head.map((cell, i) => (
                    <th
                      key={i}
                      className="border-b border-border px-2 py-1.5 font-semibold"
                      style={{ textAlign: block.align[i] ?? "left" }}
                    >
                      {renderInline(cell, `${key}-h${i}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {block.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, i) => (
                      <td key={i} className="tabular px-2 py-1.5 align-top" style={{ textAlign: block.align[i] ?? "left" }}>
                        {renderInline(cell, `${key}-${r}-${i}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      default:
        return null;
    }
  });
}

/** Renders model output as Markdown with React elements only (raw HTML is shown as text). */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = React.useMemo(() => parseMarkdown(source), [source]);
  return (
    <div className={cn("flex min-w-0 flex-col gap-2.5 break-words text-sm leading-relaxed text-fg", className)}>
      {renderBlocks(blocks)}
    </div>
  );
}
