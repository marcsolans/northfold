"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { Arrow } from "@/components/ui/primitives";
import { pad2 } from "@/lib/text";

export type Industry = { name: string; useCases: string };

/** Tonal card art from the prototype (ART). */
const ART = [
  "linear-gradient(160deg, #3a3633 0%, #070707 100%)",
  "linear-gradient(160deg, #8a847d 0%, #2e2e2e 100%)",
  "linear-gradient(160deg, #b8aea4 0%, #4a4642 100%)",
  "linear-gradient(160deg, #2e2e2e 0%, #0e0d0c 100%)",
  "linear-gradient(160deg, #a89d92 0%, #3a3633 100%)",
  "linear-gradient(160deg, #d59566 0%, #4a3a2e 100%)",
  "linear-gradient(160deg, #736f6a 0%, #1c1b1a 100%)",
];
const LATTICE =
  "repeating-linear-gradient(90deg, rgba(255,255,255,0.07) 0 1px, transparent 1px 56px), repeating-linear-gradient(0deg, rgba(255,255,255,0.07) 0 1px, transparent 1px 56px)";
const GAP = 24;

type Metrics = { step: number; max: number; at: number; pages: number; idx: number };

/**
 * Horizontal rail of square industry cards: scroll-snap, mouse drag-to-scroll,
 * prev/next, and a dot pager synced to scroll. Works in RTL (negative scrollLeft).
 */
export function IndustryRail({ items, href, labels }: { items: Industry[]; href: string; labels: { previous: string; next: string } }) {
  const railRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; left: number; moved: number; id: number } | null>(null);
  const suppressClick = useRef(false);
  // Before hydration: 4 pages is right for desktop (7 cards, 4 visible).
  const [m, setM] = useState<Metrics>({ step: 300, max: 1, at: 0, pages: 4, idx: 0 });

  const isRtl = () => railRef.current !== null && getComputedStyle(railRef.current).direction === "rtl";

  const measure = useCallback(() => {
    const rail = railRef.current;
    if (!rail) return;
    const card = rail.firstElementChild as HTMLElement | null;
    const step = card ? card.getBoundingClientRect().width + GAP : 300;
    const max = Math.max(0, rail.scrollWidth - rail.clientWidth);
    const at = Math.abs(rail.scrollLeft);
    const pages = Math.max(1, Math.round(max / step) + 1);
    const idx = Math.min(pages - 1, Math.round(at / step));
    setM((p) => (p.step === step && p.max === max && p.at === at && p.pages === pages && p.idx === idx ? p : { step, max, at, pages, idx }));
  }, []);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    let frame = 0;
    const onScroll = () => {
      if (!frame)
        frame = requestAnimationFrame(() => {
          frame = 0;
          measure();
        });
    };
    measure();
    rail.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(onScroll);
    ro.observe(rail);
    return () => {
      rail.removeEventListener("scroll", onScroll);
      ro.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [measure]);

  const scrollToPage = (i: number) => {
    const rail = railRef.current;
    if (!rail) return;
    const left = Math.max(0, Math.min(m.max, i * m.step));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    rail.scrollTo({ left: isRtl() ? -left : left, behavior: reduce ? "auto" : "smooth" });
  };

  // Drag to scroll: mouse only (touch keeps native momentum scrolling).
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    drag.current = { x: e.clientX, left: e.currentTarget.scrollLeft, moved: 0, id: e.pointerId };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    d.moved = Math.max(d.moved, Math.abs(dx));
    if (d.moved > 6 && !e.currentTarget.classList.contains("is-dragging")) {
      e.currentTarget.classList.add("is-dragging");
      e.currentTarget.setPointerCapture(d.id);
    }
    e.currentTarget.scrollLeft = d.left - dx;
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const rail = e.currentTarget;
    if (rail.hasPointerCapture(d.id)) rail.releasePointerCapture(d.id);
    if (d.moved > 6) {
      suppressClick.current = true;
      rail.classList.remove("is-dragging");
      scrollToPage(Math.round(Math.abs(rail.scrollLeft) / m.step));
    }
  };

  const atStart = m.at <= 2;
  const atEnd = m.at >= m.max - 2;
  const navBtn =
    "flex size-11 items-center justify-center border border-stone bg-white text-obsidian transition-opacity disabled:cursor-default disabled:opacity-40";

  return (
    <>
      <div
        ref={railRef}
        className="rail flex cursor-grab select-none gap-6 overflow-x-auto overscroll-x-contain [scroll-snap-type:x_proximity]"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={(e) => drag.current && endDrag(e)}
        onClickCapture={(e) => {
          if (suppressClick.current) {
            e.preventDefault();
            e.stopPropagation();
            suppressClick.current = false;
          }
        }}
      >
        {items.map((it, i) => (
          <a
            key={it.name}
            href={href}
            draggable={false}
            className="rail-card relative block aspect-square snap-start overflow-hidden text-white"
          >
            <div aria-hidden="true" className="rail-art absolute inset-0" style={{ background: ART[i % ART.length] }} />
            <div aria-hidden="true" className="absolute inset-0" style={{ backgroundImage: LATTICE }} />
            <div aria-hidden="true" className="absolute inset-0" style={{ background: "linear-gradient(rgba(18,16,14,0.1) 40%, rgba(18,16,14,0.9))" }} />
            <span aria-hidden="true" className="absolute start-[18px] top-[18px] font-mono text-[11px] tracking-[0.04em] text-white/80">
              {pad2(i + 1)}
            </span>
            <span className="absolute inset-x-[18px] bottom-[18px] flex flex-col gap-2">
              <span className="text-[21px] leading-[1.15] tracking-[-0.015em]">{it.name}</span>
              <span className="rail-cap">
                <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-white/80">{it.useCases}</span>
              </span>
            </span>
          </a>
        ))}
      </div>
      <div className="flex items-center justify-end gap-2">
        <button type="button" aria-label={labels.previous} disabled={atStart} onClick={() => scrollToPage(Math.max(0, m.idx - 1))} className={navBtn}>
          <Arrow className="rotate-180 rtl:rotate-0" />
        </button>
        <div className="flex h-11 items-center gap-0.5 border border-stone px-2.5">
          {Array.from({ length: m.pages }, (_, i) => (
            <button
              key={i}
              type="button"
              aria-label={items[i]?.name ?? String(i + 1)}
              aria-current={i === m.idx ? "true" : undefined}
              onClick={() => scrollToPage(i)}
              className="flex h-[30px] w-[22px] items-center justify-center"
            >
              <span className={`size-1.5 transition-colors duration-300 ${i === m.idx ? "bg-obsidian" : "bg-stone"}`} />
            </button>
          ))}
        </div>
        <button type="button" aria-label={labels.next} disabled={atEnd} onClick={() => scrollToPage(Math.min(m.pages - 1, m.idx + 1))} className={navBtn}>
          <Arrow className="rtl:rotate-180" />
        </button>
      </div>
    </>
  );
}
