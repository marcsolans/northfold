"use client";

import { useEffect } from "react";

/**
 * Drives `--gx` (the sheen gradient offset) on a section from the pointer position,
 * as in the prototype: x relative to the section, minus 60px. Optionally resets on leave.
 * Also pauses the hero lattice loop while the section is off-screen.
 */
export function PointerSheen({ targetId, resetTo }: { targetId: string; resetTo?: number }) {
  useEffect(() => {
    const el = document.getElementById(targetId);
    if (!el) return;
    let frame = 0;
    let x = 0;
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      x = e.clientX - el.getBoundingClientRect().left - 60;
      if (!frame)
        frame = requestAnimationFrame(() => {
          frame = 0;
          el.style.setProperty("--gx", `${Math.round(x)}px`);
        });
    };
    const onLeave = () => {
      if (resetTo !== undefined) el.style.setProperty("--gx", `${resetTo}px`);
    };
    el.addEventListener("pointermove", onMove, { passive: true });
    el.addEventListener("pointerleave", onLeave);

    // The lattice is server-rendered paused; start it once the page is idle (keeps the
    // 18s loop out of the load window), then pause it whenever the hero is off-screen.
    const lattice = el.querySelector<HTMLElement>("[data-hero-lattice]");
    let io: IntersectionObserver | null = null;
    let idle = 0;
    if (lattice) {
      const start = () => {
        io = new IntersectionObserver(([e]) => lattice.toggleAttribute("data-paused", !e.isIntersecting));
        io.observe(el);
      };
      const ric = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 600));
      idle = ric(start, { timeout: 2000 });
    }

    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      io?.disconnect();
      (window.cancelIdleCallback ?? clearTimeout)(idle);
      cancelAnimationFrame(frame);
    };
  }, [targetId, resetTo]);
  return null;
}
