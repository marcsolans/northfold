"use client";

import { useEffect, useRef } from "react";

export type Stat = { value: number; suffix: string; label: string };

/**
 * Stat cells that count up once on view (1.2s ease-out cubic, all in sync).
 * Server HTML carries the final values; each number reserves the final value's
 * width in a hidden grid layer, so counting never shifts layout. Motion is loaded
 * only when the panel scrolls into view.
 */
export function StatCounters({ stats }: { stats: Stat[] }) {
  const listRef = useRef<HTMLDListElement>(null);
  const numRefs = useRef<Array<HTMLSpanElement | null>>([]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const set = (k: number) =>
      numRefs.current.forEach((el, i) => {
        if (el) el.textContent = String(Math.round(stats[i].value * k));
      });

    let stop: (() => void) | undefined;
    let cancelled = false;
    const start = async () => {
      const { animate } = await import("motion");
      if (cancelled) return;
      const controls = animate(0, 1, {
        duration: 1.2,
        ease: (p: number) => 1 - Math.pow(1 - p, 3),
        onUpdate: set,
      });
      stop = () => controls.stop();
    };

    const vh = window.innerHeight;
    const trigger = (top: number) => top < vh * 0.85;
    if (trigger(list.getBoundingClientRect().top)) {
      set(0);
      start();
      return () => {
        cancelled = true;
        stop?.();
      };
    }
    set(0); // below the fold: reset while invisible, count up on arrival
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        io.disconnect();
        start();
      },
      { rootMargin: "0px 0px -15% 0px" },
    );
    io.observe(list);
    return () => {
      cancelled = true;
      io.disconnect();
      stop?.();
    };
  }, [stats]);

  return (
    <dl ref={listRef} className="m-0 grid grid-cols-2 gap-px lg:grid-cols-4">
      {stats.map((s, i) => (
        <div key={s.label} className="flex flex-col-reverse gap-2 bg-signal px-6 py-7 md:px-9">
          <dt className="max-w-[24em] font-mono text-[10px] uppercase leading-normal tracking-[0.1em] text-concrete-deep">{s.label}</dt>
          <dd className="m-0 text-[34px] leading-[1.3] tracking-[0.005em] tabular-nums text-obsidian md:text-[40px]">
            <span className="sr-only">
              {s.value}
              {s.suffix}
            </span>
            {/* Number + suffix stay in LTR order (5×, 100%) in RTL locales too. */}
            <span aria-hidden="true" dir="ltr" className="inline-block">
              <span className="inline-grid">
                <span className="invisible [grid-area:1/1]">{s.value}</span>
                <span
                  ref={(el) => {
                    numRefs.current[i] = el;
                  }}
                  className="[grid-area:1/1]"
                >
                  {s.value}
                </span>
              </span>
              <span>{s.suffix}</span>
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
