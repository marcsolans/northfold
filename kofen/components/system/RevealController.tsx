"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * Scroll reveals (opacity 0 / translateY 16px → visible, 600ms out-soft, once).
 *
 * Server HTML renders every `[data-reveal]` element visible. After hydration this
 * controller leaves elements already near the viewport untouched, marks the rest
 * `data-reveal="pending"` (hidden by CSS only while `html[data-motion]` is set) and
 * reveals them as they scroll in. Without JS, or with reduced motion, nothing hides.
 */
export function RevealController() {
  const pathname = usePathname();

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const els = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]:not([data-reveal='in'])"));
    if (!els.length) return;

    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          (e.target as HTMLElement).dataset.reveal = "in";
          io.unobserve(e.target);
        }
      },
      // Same trigger as the prototype: element top above (viewport bottom − 100px).
      { rootMargin: "0px 0px -100px 0px", threshold: 0 },
    );

    // Read every position first, then write: interleaving would force a layout per element.
    const vh = window.innerHeight;
    const tops = els.map((el) => el.getBoundingClientRect().top);
    els.forEach((el, i) => {
      if (tops[i] < vh - 100) {
        el.dataset.reveal = "in";
      } else {
        el.dataset.reveal = "pending";
        io.observe(el);
      }
    });
    document.documentElement.dataset.motion = "";
    return () => io.disconnect();
  }, [pathname]);

  return null;
}
