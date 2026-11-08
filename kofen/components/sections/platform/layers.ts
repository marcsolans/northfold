/** Kofen layers diagram: values as a pure function of scroll progress p ∈ [0, 1] (prototype renderVals). */
const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const seg = (p: number, a: number, b: number) => clamp01((p - a) / (b - a));

export type LayersState = {
  /** stroke-dashoffset per ring (outer → core) */
  o1: number;
  o2: number;
  o3: number;
  o4: number;
  /** spokes stroke-dashoffset */
  s: number;
  /** fill-opacity per ring */
  f1: number;
  f2: number;
  f3: number;
  f4: number;
  /** outer edge: solid stroke opacity / dashed overlay opacity */
  solid: number;
  dash: number;
  /** labels + core marker opacity */
  lb: number;
};

export function layersAt(p: number): LayersState {
  const fs = seg(p, 0.55, 0.72);
  return {
    o1: Math.round(1840 * (1 - seg(p, 0, 0.25))),
    o2: Math.round(1320 * (1 - seg(p, 0.15, 0.4))),
    o3: Math.round(800 * (1 - seg(p, 0.3, 0.52))),
    o4: Math.round(304 * (1 - seg(p, 0.42, 0.6))),
    s: Math.round(272 * (1 - seg(p, 0.35, 0.6))),
    f1: +(0.7 * fs).toFixed(2),
    f2: +(0.55 * seg(p, 0.58, 0.75)).toFixed(2),
    f3: +seg(p, 0.6, 0.78).toFixed(2),
    f4: +seg(p, 0.62, 0.8).toFixed(2),
    solid: +(1 - fs).toFixed(2),
    dash: +fs.toFixed(2),
    lb: +seg(p, 0.7, 0.85).toFixed(2),
  };
}

/** Progress of the #deployment section: 0 when its top reaches 90% of the viewport. */
export function progressFor(rect: DOMRect, vh: number) {
  return clamp01((vh * 0.9 - rect.top) / Math.max(400, Math.min(rect.height, vh * 1.4)));
}
