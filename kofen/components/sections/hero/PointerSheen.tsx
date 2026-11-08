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

    const lattice = el.querySelector<HTMLElement>("[data-hero-lattice]");
    const io = lattice
      ? new IntersectionObserver(([e]) => lattice.toggleAttribute("data-paused", !e.isIntersecting))
      : null;
    if (lattice) io!.observe(el);

    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      io?.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [targetId, resetTo]);
  return null;
}
