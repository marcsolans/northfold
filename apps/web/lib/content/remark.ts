/**
 * Small remark plugins (no extra dependencies):
 * - `remarkTables`: GitHub-style pipe tables (CommonMark parses them as paragraphs).
 * - `remarkHeadings`: stable ids on headings + table of contents (h2/h3).
 * - `remarkLinks`: rewrite links to sibling `.md` files into site routes.
 */

export interface MdNode {
  type: string;
  children?: MdNode[];
  value?: string;
  url?: string;
  title?: string | null;
  depth?: number;
  align?: ("left" | "right" | "center" | null)[];
  position?: { start: { offset?: number }; end: { offset?: number } };
  data?: { hProperties?: Record<string, unknown>; [key: string]: unknown };
}

interface VFileLike {
  value?: unknown;
}

export interface TocEntry {
  depth: 2 | 3;
  text: string;
  id: string;
}

function walk(node: MdNode, visit: (node: MdNode, index: number, parent: MdNode) => void): void {
  const children = node.children;
  if (!children) return;
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (!child) continue;
    visit(child, i, node);
    walk(children[i] ?? child, visit);
  }
}

export function nodeText(node: MdNode): string {
  if (node.value !== undefined && (node.type === "text" || node.type === "inlineCode")) return node.value;
  return (node.children ?? []).map(nodeText).join("");
}

export function slugify(text: string): string {
  return (
    text
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/[\s-]+/g, "-")
      .slice(0, 80) || "seccion"
  );
}

// ------------------------------------------------------------------ inline parser for table cells

const INLINE_PATTERNS: { re: RegExp; build: (m: RegExpExecArray) => MdNode }[] = [
  { re: /`([^`]+)`/, build: (m) => ({ type: "inlineCode", value: m[1] ?? "" }) },
  {
    re: /\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/,
    build: (m) => ({ type: "link", url: m[2] ?? "", title: m[3] ?? null, children: parseInline(m[1] ?? "") }),
  },
  { re: /\*\*([^*]+)\*\*/, build: (m) => ({ type: "strong", children: parseInline(m[1] ?? "") }) },
  { re: /(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])/, build: (m) => ({ type: "emphasis", children: parseInline(m[1] ?? "") }) },
  { re: /(?<![\w_])_([^_\s][^_]*)_(?![\w_])/, build: (m) => ({ type: "emphasis", children: parseInline(m[1] ?? "") }) },
];

function unescape(text: string): string {
  return text.replace(/\\([\\`*_{}[\]()#+\-.!|])/g, "$1");
}

export function parseInline(text: string): MdNode[] {
  const nodes: MdNode[] = [];
  let rest = text;
  while (rest) {
    let best: { index: number; length: number; node: MdNode } | null = null;
    for (const { re, build } of INLINE_PATTERNS) {
      const m = re.exec(rest);
      if (m && (best === null || m.index < best.index)) best = { index: m.index, length: m[0].length, node: build(m) };
    }
    if (best === null) {
      nodes.push({ type: "text", value: unescape(rest) });
      break;
    }
    if (best.index > 0) nodes.push({ type: "text", value: unescape(rest.slice(0, best.index)) });
    nodes.push(best.node);
    rest = rest.slice(best.index + best.length);
  }
  return nodes;
}

// ------------------------------------------------------------------ tables

const DELIMITER_ROW = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/;

function splitRow(line: string): string[] {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  for (let i = 0; i < row.length; i++) {
    const ch = row[i];
    if (ch === "\\" && row[i + 1] === "|") {
      current += "\\|";
      i++;
    } else if (ch === "|") {
      cells.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  cells.push(current.trim());
  return cells;
}

export function parseTable(raw: string): MdNode | null {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter((l) => l !== "");
  const [headerLine, delimiterLine] = lines;
  if (!headerLine || !delimiterLine || !headerLine.includes("|") || !DELIMITER_ROW.test(delimiterLine)) return null;
  const header = splitRow(headerLine);
  const delimiters = splitRow(delimiterLine);
  if (header.length !== delimiters.length) return null;
  const align = delimiters.map((d) => {
    const left = d.startsWith(":");
    const right = d.endsWith(":");
    return left && right ? "center" : right ? "right" : left ? "left" : null;
  });
  const rows = [header, ...lines.slice(2).map(splitRow)].map((cells) => {
    const normalized = header.map((_, i) => cells[i] ?? "");
    return {
      type: "tableRow",
      children: normalized.map((cell) => ({ type: "tableCell", children: parseInline(cell) })),
    } satisfies MdNode;
  });
  return { type: "table", align, children: rows };
}

export function remarkTables() {
  return (tree: MdNode, file: VFileLike) => {
    const source = typeof file.value === "string" ? file.value : String(file.value ?? "");
    walk(tree, (node, index, parent) => {
      if (node.type !== "paragraph" || !parent.children) return;
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (start === undefined || end === undefined) return;
      const table = parseTable(source.slice(start, end));
      if (table) parent.children[index] = table;
    });
  };
}

// ------------------------------------------------------------------ headings

export function remarkHeadings(options: { toc: TocEntry[] }) {
  return (tree: MdNode) => {
    const used = new Map<string, number>();
    walk(tree, (node) => {
      if (node.type !== "heading") return;
      const text = nodeText(node).trim();
      const base = slugify(text);
      const count = used.get(base) ?? 0;
      used.set(base, count + 1);
      const id = count ? `${base}-${count + 1}` : base;
      node.data = { ...node.data, hProperties: { ...(node.data?.hProperties ?? {}), id } };
      if (node.depth === 2 || node.depth === 3) options.toc.push({ depth: node.depth, text, id });
    });
  };
}

// ------------------------------------------------------------------ links

export function remarkLinks(options: { rewrite: (url: string) => string }) {
  return (tree: MdNode) => {
    walk(tree, (node) => {
      if ((node.type === "link" || node.type === "definition") && node.url) node.url = options.rewrite(node.url);
    });
  };
}
