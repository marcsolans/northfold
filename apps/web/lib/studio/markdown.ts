/**
 * Minimal, safe Markdown parser for model output. It produces a small AST that is rendered with React
 * elements (never `dangerouslySetInnerHTML`): raw HTML stays literal text and only http(s), mailto and
 * relative links are kept. Tolerant of partial input while tokens stream in (an open code fence runs to the end).
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "del"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "br" };

export type Align = "left" | "center" | "right" | null;

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: 1 | 2 | 3 | 4 | 5 | 6; c: Inline[] }
  | { t: "code"; lang: string; v: string }
  | { t: "quote"; c: Block[] }
  | { t: "list"; ordered: boolean; start: number; items: Block[][] }
  | { t: "hr" }
  | { t: "table"; align: Align[]; head: Inline[][]; rows: Inline[][][] };

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
const QUOTE = /^ {0,3}>\s?/;
const LIST_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$/;

function isBlank(line: string): boolean {
  return line.trim() === "";
}

function indentOf(line: string): number {
  const m = /^(\s*)/.exec(line);
  return m?.[1]?.replace(/\t/g, "    ").length ?? 0;
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    QUOTE.test(line) ||
    LIST_ITEM.test(line) ||
    (line.includes("|") && next !== undefined && TABLE_SEP.test(next) && next.includes("-"))
  );
}

function splitRow(line: string): string[] {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  for (let i = 0; i < row.length; i++) {
    const ch = row[i];
    if (ch === "\\" && row[i + 1] === "|") {
      current += "|";
      i++;
    } else if (ch === "|") {
      cells.push(current.trim());
      current = "";
    } else current += ch;
  }
  cells.push(current.trim());
  return cells;
}

function parseList(lines: string[], start: number): { block: Block; next: number } {
  const first = LIST_ITEM.exec(lines[start] ?? "");
  const baseIndent = indentOf(lines[start] ?? "");
  const marker = first?.[2] ?? "-";
  const ordered = /\d/.test(marker);
  const startNum = ordered ? Number.parseInt(marker, 10) : 1;
  const items: string[][] = [];
  let i = start;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const m = LIST_ITEM.exec(line);
    if (m && indentOf(line) <= baseIndent + 1 && /\d/.test(m[2] ?? "") === ordered) {
      items.push([m[3] ?? ""]);
      i++;
      continue;
    }
    if (items.length === 0) break;
    const current = items[items.length - 1] as string[];
    if (isBlank(line)) {
      const nextLine = lines[i + 1];
      if (nextLine !== undefined && (indentOf(nextLine) > baseIndent || (LIST_ITEM.test(nextLine) && indentOf(nextLine) <= baseIndent + 1))) {
        current.push("");
        i++;
        continue;
      }
      break;
    }
    if (indentOf(line) > baseIndent) {
      current.push(line.replace(new RegExp(`^\\s{0,${baseIndent + 4}}`), ""));
      i++;
      continue;
    }
    // Lazy continuation of the item paragraph.
    if (!startsBlock(line, lines[i + 1])) {
      current.push(line.trim());
      i++;
      continue;
    }
    break;
  }
  return { block: { t: "list", ordered, start: startNum, items: items.map((item) => parseBlockLines(item)) }, next: i };
}

function parseBlockLines(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (isBlank(line)) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const token = fence[1] ?? "```";
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").trim().startsWith(token.slice(0, 3)) ) {
        body.push(lines[i] ?? "");
        i++;
      }
      i++; // closing fence (or end of input while streaming)
      blocks.push({ t: "code", lang: fence[2] ?? "", v: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const level = Math.min(6, (heading[1] ?? "#").length) as 1 | 2 | 3 | 4 | 5 | 6;
      blocks.push({ t: "h", level, c: parseInline(heading[2] ?? "") });
      i++;
      continue;
    }
    if (HR.test(line)) {
      blocks.push({ t: "hr" });
      i++;
      continue;
    }
    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i] ?? "")) {
        body.push((lines[i] ?? "").replace(QUOTE, ""));
        i++;
      }
      blocks.push({ t: "quote", c: parseBlockLines(body) });
      continue;
    }
    if (LIST_ITEM.test(line)) {
      const { block, next } = parseList(lines, i);
      blocks.push(block);
      i = Math.max(next, i + 1);
      continue;
    }
    const nextLine = lines[i + 1];
    if (line.includes("|") && nextLine !== undefined && TABLE_SEP.test(nextLine) && nextLine.includes("-")) {
      const head = splitRow(line);
      const align: Align[] = splitRow(nextLine).map((cell) => {
        const left = cell.startsWith(":");
        const right = cell.endsWith(":");
        return left && right ? "center" : right ? "right" : left ? "left" : null;
      });
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && !isBlank(lines[i] ?? "") && (lines[i] ?? "").includes("|")) {
        const cells = splitRow(lines[i] ?? "");
        rows.push(head.map((_, idx) => parseInline(cells[idx] ?? "")));
        i++;
      }
      blocks.push({ t: "table", align: head.map((_, idx) => align[idx] ?? null), head: head.map((h) => parseInline(h)), rows });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && !isBlank(lines[i] ?? "") && (para.length === 0 || !startsBlock(lines[i] ?? "", lines[i + 1]))) {
      para.push(lines[i] ?? "");
      i++;
    }
    blocks.push({ t: "p", c: parseInline(para.join("\n")) });
  }
  return blocks;
}

export function parseMarkdown(source: string): Block[] {
  return parseBlockLines(source.replace(/\r\n?/g, "\n").split("\n"));
}

// ------------------------------------------------------------------------------------ inline

const PUNCT = /[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/;
const LINK = /^\[((?:[^\][]|\[[^\]]*\])*)\]\(\s*<?([^\s)>]+)>?(?:\s+"[^"]*")?\s*\)/;
const AUTOLINK = /^<((?:https?:\/\/|mailto:)[^\s>]+)>/;
const BARE_URL = /^https?:\/\/[^\s<>"]+/;

/** Only http(s), mailto and relative links survive; anything else (javascript:, data:, …) is dropped. */
export function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (/^(https?:|mailto:)/i.test(href)) return href;
  if (href.startsWith("/") && !href.startsWith("//")) return href;
  if (href.startsWith("#")) return href;
  return null;
}

function findClosing(src: string, from: number, delim: string): number {
  let idx = src.indexOf(delim, from);
  while (idx !== -1) {
    const before = src[idx - 1];
    if (idx > from && before !== " " && before !== "\n" && before !== "\\") {
      if (delim === "_" || delim === "__") {
        const after = src[idx + delim.length];
        if (after === undefined || !/[\p{L}\p{N}]/u.test(after)) return idx;
      } else return idx;
    }
    idx = src.indexOf(delim, idx + 1);
  }
  return -1;
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text) out.push({ t: "text", v: text });
    text = "";
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i] ?? "";
    const rest = src.slice(i);
    if (ch === "\\" && PUNCT.test(src[i + 1] ?? "")) {
      text += src[i + 1];
      i += 2;
      continue;
    }
    if (ch === "\\" && src[i + 1] === "\n") {
      flush();
      out.push({ t: "br" });
      i += 2;
      continue;
    }
    if (ch === "\n") {
      text = text.replace(/ +$/, "");
      flush();
      out.push({ t: "br" });
      i++;
      continue;
    }
    if (ch === "`") {
      const run = /^`+/.exec(rest)?.[0] ?? "`";
      const close = src.indexOf(run, i + run.length);
      if (close !== -1) {
        flush();
        out.push({ t: "code", v: src.slice(i + run.length, close).replace(/^ (.*) $/s, "$1") });
        i = close + run.length;
        continue;
      }
    }
    if (ch === "[") {
      const m = LINK.exec(rest);
      if (m) {
        const href = safeHref(m[2] ?? "");
        flush();
        const children = parseInline(m[1] ?? "");
        if (href) out.push({ t: "link", href, c: children });
        else out.push(...children);
        i += m[0].length;
        continue;
      }
    }
    if (ch === "<") {
      const m = AUTOLINK.exec(rest);
      if (m) {
        flush();
        out.push({ t: "link", href: m[1] ?? "", c: [{ t: "text", v: m[1] ?? "" }] });
        i += m[0].length;
        continue;
      }
    }
    if ((ch === "h" || ch === "H") && !/[\p{L}\p{N}]/u.test(src[i - 1] ?? "")) {
      const m = BARE_URL.exec(rest);
      if (m) {
        const url = m[0].replace(/[.,:;!?'")\]]+$/, "");
        flush();
        out.push({ t: "link", href: url, c: [{ t: "text", v: url }] });
        i += url.length;
        continue;
      }
    }
    if (ch === "~" && src[i + 1] === "~") {
      const close = findClosing(src, i + 2, "~~");
      if (close !== -1) {
        flush();
        out.push({ t: "del", c: parseInline(src.slice(i + 2, close)) });
        i = close + 2;
        continue;
      }
    }
    if (ch === "*" || ch === "_") {
      const leftOk = ch === "*" || !/[\p{L}\p{N}]/u.test(src[i - 1] ?? "");
      const double = src[i + 1] === ch;
      const delim = double ? ch + ch : ch;
      const nextCh = src[i + delim.length];
      if (leftOk && nextCh !== undefined && nextCh !== " " && nextCh !== "\n") {
        const close = findClosing(src, i + delim.length, delim);
        if (close !== -1) {
          flush();
          const inner = parseInline(src.slice(i + delim.length, close));
          out.push(double ? { t: "strong", c: inner } : { t: "em", c: inner });
          i = close + delim.length;
          continue;
        }
      }
    }
    text += ch;
    i++;
  }
  flush();
  return out;
}
