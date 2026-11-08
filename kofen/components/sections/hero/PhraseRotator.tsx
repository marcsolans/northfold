"use client";

import { useEffect, useState } from "react";

const START = 900; // ms after hydration before the first phrase is counted
const STEP = 1700; // ms per phrase
const SETTLE = 600; // ms for the last phrase to hand back to phrase 1

/**
 * Second hero line: cycles through the phrases once (slide/blur swap every 1.7s),
 * then rests on phrase 1. Phrases share one grid cell, so the height never changes.
 * aria-hidden: screen readers get phrase 1 inside the <h1>.
 */
export function PhraseRotator({ phrases }: { phrases: string[] }) {
  const [state, setState] = useState({ idx: 0, prev: -1 });

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const n = phrases.length;
    const timers: number[] = [];
    for (let k = 1; k < n; k++) timers.push(window.setTimeout(() => setState({ idx: k, prev: k - 1 }), START + k * STEP));
    timers.push(window.setTimeout(() => setState({ idx: 0, prev: n - 1 }), START + n * STEP));
    timers.push(window.setTimeout(() => setState({ idx: 0, prev: -1 }), START + n * STEP + SETTLE));
    return () => timers.forEach(clearTimeout);
  }, [phrases.length]);

  return (
    <div aria-hidden="true" className="rotator -mb-[0.1em] grid overflow-hidden pb-[0.22em]">
      {phrases.map((text, i) => {
        const active = i === state.idx;
        return (
          <span
            key={i}
            className="text-concrete text-balance"
            style={{
              opacity: active ? 1 : 0.001,
              transform: `translateY(${active ? "0" : i === state.prev ? "-70%" : "70%"})`,
              filter: `blur(${active ? 0 : 4}px)`,
            }}
          >
            {text}
          </span>
        );
      })}
    </div>
  );
}
