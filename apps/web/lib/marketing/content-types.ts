/** Shapes of the structured copy read with `t.raw()` from messages/<locale>/marketing.json. */

export interface Pillar {
  key: string;
  title: string;
  body: string;
  points: string[];
}

export interface SecurityItem {
  key: string;
  title: string;
  body: string;
}

export interface SecuritySection extends SecurityItem {
  points: string[];
}

export interface TemplateItem {
  id: string;
  sector: string;
  title: string;
  body: string;
  includes: string[];
}

export interface UseCase {
  team: string;
  examples: string[];
}

export interface FaqItem {
  q: string;
  a: string;
}
