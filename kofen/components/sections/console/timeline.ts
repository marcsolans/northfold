/**
 * Live console timeline: a pure function of the playhead, ported from the
 * prototype's renderVals(). All times in ms.
 */
export const SCENE_MS = 13200;
export const SCENES = 3;
export const TOTAL_MS = SCENE_MS * SCENES;
export const T_SOURCE = 120;
export const T_AGENT = 650;
export const T_STEPS = [1200, 2000, 2800] as const;
export const T_TYPE = 3500;
export const MS_PER_CHAR = 24;
export const T_DONE = 11200;
/** Resting playhead for reduced motion / no JS: scene 1, approved. */
export const RESTING_T = T_DONE + 400;

export type StepState = "hidden" | "busy" | "done";

export type SceneFrame = {
  scene: number;
  /** ms into the current scene */
  local: number;
  showSource: boolean;
  showAgent: boolean;
  working: boolean;
  steps: StepState[];
  showReply: boolean;
  typedChars: number;
  typing: boolean;
  showCard: boolean;
  done: boolean;
};

/** Frame for playhead `t` given each scene's reply length (in code points). */
export function frameAt(t: number, replyLengths: number[]): SceneFrame {
  const scene = Math.floor(t / SCENE_MS) % SCENES;
  const local = t - scene * SCENE_MS;
  const chars = replyLengths[scene] ?? 0;
  const typedChars = Math.min(chars, Math.max(0, Math.floor((local - T_TYPE) / MS_PER_CHAR)));
  const cardAt = T_TYPE + chars * MS_PER_CHAR + 250;
  const steps = T_STEPS.map((start, i): StepState => {
    const end = T_STEPS[i + 1] ?? T_TYPE;
    if (local < start) return "hidden";
    return local < end ? "busy" : "done";
  });
  return {
    scene,
    local,
    showSource: local >= T_SOURCE,
    showAgent: local >= T_AGENT,
    working: local >= T_AGENT && local < cardAt,
    steps,
    showReply: local >= T_TYPE,
    typedChars,
    typing: local >= T_TYPE && typedChars < chars,
    showCard: local >= cardAt,
    done: local >= T_DONE,
  };
}

/** Stable key: the console only re-renders when this changes. */
export const frameKey = (f: SceneFrame) =>
  [f.scene, +f.showSource, +f.showAgent, +f.working, f.steps.join(""), +f.showReply, f.typedChars, +f.showCard, +f.done].join("|");

/** "m:ss" as in the prototype's clock. */
export function mmss(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Composer placeholder typewriter: type 42ms/char, hold 2.6s, delete 22ms/char,
 * pause 0.5s, next phrase. Driven by the console clock.
 */
export function placeholderAt(clock: number, phrases: string[]): string {
  const segs = phrases.map((p) => {
    const chars = Array.from(p);
    const n = chars.length;
    return { chars, n, d: n * 42 + 2600 + n * 22 + 500 };
  });
  const cycle = segs.reduce((a, s) => a + s.d, 0);
  let r = clock % cycle;
  let j = 0;
  while (r >= segs[j].d) {
    r -= segs[j].d;
    j++;
  }
  const { chars, n } = segs[j];
  let shown: number;
  if (r < n * 42) shown = Math.floor(r / 42);
  else if (r < n * 42 + 2600) shown = n;
  else if (r < n * 42 + 2600 + n * 22) shown = n - Math.floor((r - n * 42 - 2600) / 22);
  else shown = 0;
  return chars.slice(0, shown).join("");
}

/** "Click a view" hint window, on the console clock. */
export const hintVisible = (clock: number, hinted: boolean) => !hinted && clock > 1200 && clock < 9000;
