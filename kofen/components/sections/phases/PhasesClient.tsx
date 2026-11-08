"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { pad2 } from "@/lib/text";

export type Phase = { title: string; kofenShare: number; body: string; chips: string[] };

const STEP_MS = 6500;

/**
 * Numbered mono stepper (tabs). Autoplays every 6.5s with a rust progress hairline,
 * only while on screen; any click or arrow key stops the autoplay for good.
 */
export function PhasesClient({ phases, tabLabel, ledByKofen, listLabel }: { phases: Phase[]; tabLabel: string; ledByKofen: string; listLabel: string }) {
  const [active, setActive] = useState(0);
  const [manual, setManual] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const manualRef = useRef(false);
  const uid = useId();

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // No autoplay: the hairline shows complete, as after a manual pick.
      manualRef.current = true;
      if (barRef.current) barRef.current.style.width = "100%";
      return;
    }
    let raf = 0;
    let last = 0;
    let clock = 0;
    let idx = 0;
    let visible = false;
    const step = (now: number) => {
      raf = 0;
      if (manualRef.current) return;
      clock += last ? Math.min(now - last, 250) : 0;
      last = now;
      const next = Math.floor(clock / STEP_MS) % phases.length;
      if (next !== idx) {
        idx = next;
        setActive(next);
      }
      if (barRef.current) barRef.current.style.width = `${(((clock % STEP_MS) / STEP_MS) * 100).toFixed(1)}%`;
      raf = requestAnimationFrame(step);
    };
    const update = () => {
      const run = visible && !document.hidden && !manualRef.current;
      if (run && !raf) {
        last = 0;
        raf = requestAnimationFrame(step);
      } else if (!run && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      update();
    });
    io.observe(root);
    document.addEventListener("visibilitychange", update);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", update);
      cancelAnimationFrame(raf);
    };
  }, [phases.length]);

  const pick = (i: number, focus = false) => {
    manualRef.current = true;
    setManual(true);
    setActive(i);
    if (focus) tabRefs.current[i]?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = phases.length;
    const map: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    const rtl = getComputedStyle(e.currentTarget).direction === "rtl";
    if (e.key in map) {
      e.preventDefault();
      const d = (e.key.startsWith("Arrow") && (e.key === "ArrowRight" || e.key === "ArrowLeft") && rtl ? -1 : 1) * map[e.key];
      pick((active + d + n) % n, true);
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      pick(e.key === "Home" ? 0 : n - 1, true);
    }
  };

  const phase = phases[active];
  const tabId = (i: number) => `${uid}-tab-${i}`;
  const panelId = `${uid}-panel`;

  return (
    <div ref={rootRef} className="flex flex-col gap-11">
      <div role="tablist" aria-label={listLabel} onKeyDown={onKey} className="flex flex-wrap gap-2">
        {phases.map((p, i) => {
          const on = i === active;
          return (
            <button
              key={p.title}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              id={tabId(i)}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={panelId}
              tabIndex={on ? 0 : -1}
              onClick={() => pick(i)}
              className={`relative min-h-11 border px-[18px] font-mono text-[11px] uppercase tracking-[0.04em] transition-colors duration-300 ${
                on ? "border-obsidian text-obsidian" : "border-[var(--line-60)] text-concrete hover:text-obsidian"
              }`}
            >
              {pad2(i + 1)} · {tabLabel}
              <span
                aria-hidden="true"
                className={`absolute -bottom-3 left-1/2 size-1.5 -translate-x-1/2 transition-colors duration-300 ${on ? "bg-rust" : "bg-transparent"}`}
              />
            </button>
          );
        })}
      </div>
      <div aria-hidden="true" className="mt-2 h-px bg-hairline">
        <div ref={barRef} className="h-px bg-rust" style={{ width: manual ? "100%" : "0%" }} />
      </div>
      <div id={panelId} role="tabpanel" aria-labelledby={tabId(active)} className="flex flex-wrap gap-x-20 gap-y-8">
        <div className="flex min-w-0 flex-[1_1_460px] flex-col gap-[18px]">
          <h3 className="m-0 text-[clamp(24px,2.2vw,30px)] font-normal leading-[1.15] tracking-[-0.025em]">{phase.title}</h3>
          <p className="m-0 max-w-[34em] text-[15.5px] leading-[1.65] text-concrete">{phase.body}</p>
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {phase.chips.map((c) => (
              <li key={c} className="chip border border-[rgba(184,174,164,0.8)] px-2.5 py-1 text-[11.5px] text-carbon">
                {c}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex min-w-0 flex-[1_1_360px] flex-col justify-center gap-3.5">
          <div className="flex items-baseline justify-between gap-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-concrete">{ledByKofen}</span>
            <span className="text-[64px] tracking-[-0.05em] tabular-nums text-obsidian">
              {phase.kofenShare}
              <span className="text-rust-deep">%</span>
            </span>
          </div>
          <div
            role="meter"
            aria-label={ledByKofen}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={phase.kofenShare}
            className="h-1 overflow-hidden bg-hairline"
          >
            <div className="h-1 bg-obsidian transition-[width] duration-500 ease-brand" style={{ width: `${phase.kofenShare}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
