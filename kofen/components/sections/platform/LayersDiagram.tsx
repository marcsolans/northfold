"use client";

import { useEffect, useRef } from "react";
import { layersAt, progressFor, type LayersState } from "./layers";

type Target = { key: keyof LayersState; prop: string };

/**
 * "Kofen layers": concentric squares (your systems → governance → agents → Kofen core)
 * plus forward-deployed engineers. Assembles as a pure function of scroll progress:
 * outer stroke draws, then inner rings, spokes, fills, labels; the outer edge crossfades
 * to dashed. Server HTML is the assembled state (no JS / reduced motion).
 */
export function LayersDiagram({ sectionId, label }: { sectionId: string; label: string }) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    const section = document.getElementById(sectionId);
    if (!svg || !section || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const targets = Array.from(svg.querySelectorAll<SVGElement>("[data-l]")).map((el) => ({
      el,
      binds: (el.dataset.l ?? "").split(" ").map((pair) => {
        const [prop, key] = pair.split(":");
        return { prop, key } as Target;
      }),
    }));

    let frame = 0;
    const render = () => {
      frame = 0;
      const s = layersAt(progressFor(section.getBoundingClientRect(), window.innerHeight));
      for (const { el, binds } of targets) for (const b of binds) el.style.setProperty(b.prop, String(s[b.key]));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(render);
    };
    render();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, [sectionId]);

  const s = layersAt(1);
  const spoke = { strokeDasharray: 272, strokeDashoffset: s.s };
  const mono = "'Geist Mono', var(--font-geist-mono), ui-monospace, monospace";

  return (
    <svg
      ref={svgRef}
      role="img"
      aria-label={label}
      viewBox="40 40 520 520"
      className="block h-auto w-full max-w-[620px] overflow-visible"
    >
      <rect x="70" y="70" width="460" height="460" fill="#ffffff" stroke="#070707" strokeWidth="1"
        data-l="fill-opacity:f1 stroke-dashoffset:o1 stroke-opacity:solid"
        style={{ fillOpacity: s.f1, strokeDasharray: 1840, strokeDashoffset: s.o1, strokeOpacity: s.solid }} />
      <rect x="70" y="70" width="460" height="460" fill="none" stroke="#070707" strokeWidth="1" strokeDasharray="3 3"
        data-l="opacity:dash" style={{ opacity: s.dash }} />
      <rect x="135" y="135" width="330" height="330" fill="#b8aea4" stroke="#070707" strokeWidth="1"
        data-l="fill-opacity:f2 stroke-dashoffset:o2"
        style={{ fillOpacity: s.f2, strokeDasharray: 1320, strokeDashoffset: s.o2 }} />
      <rect x="200" y="200" width="200" height="200" fill="#2e2e2e" stroke="#070707" strokeWidth="1"
        data-l="fill-opacity:f3 stroke-dashoffset:o3"
        style={{ fillOpacity: s.f3, strokeDasharray: 800, strokeDashoffset: s.o3 }} />
      <rect x="262" y="262" width="76" height="76" fill="#ffffff" stroke="#070707" strokeWidth="1"
        data-l="fill-opacity:f4 stroke-dashoffset:o4"
        style={{ fillOpacity: s.f4, strokeDasharray: 304, strokeDashoffset: s.o4 }} />
      <g stroke="#070707" strokeWidth="1" fill="none">
        <path d="M262 262 L70 70" data-l="stroke-dashoffset:s" style={spoke} />
        <path d="M338 262 L530 70" data-l="stroke-dashoffset:s" style={spoke} />
        <path d="M338 338 L530 530" data-l="stroke-dashoffset:s" style={spoke} />
        <path d="M262 338 L70 530" data-l="stroke-dashoffset:s" style={spoke} />
      </g>
      <rect x="296" y="296" width="8" height="8" fill="#d59566" data-l="opacity:lb" style={{ opacity: s.lb }} />
      <g fontFamily={mono} letterSpacing="0.02em" data-l="opacity:lb" style={{ opacity: s.lb }} aria-hidden="true">
        <text x="84" y="94" fontSize="10.5" fill="#070707">YOUR SYSTEMS</text>
        <text x="84" y="108" fontSize="7.4" fill="#736f6a">ERP · CRM · DATA · CHANNELS</text>
        <text x="149" y="158" fontSize="10.5" fill="#070707">GOVERNANCE</text>
        <text x="149" y="172" fontSize="7.4" fill="#2e2e2e">EVALS · PERMISSIONS · AUDIT</text>
        <text x="214" y="222" fontSize="10.5" fill="#ffffff">AGENTS</text>
        <text x="214" y="236" fontSize="7.4" fill="#dad5cc">VOICE · DOCUMENTS · WORKFLOWS</text>
        <text x="300" y="326" fontSize="9" fill="#070707" textAnchor="middle">KOFEN</text>
        <text x="516" y="512" fontSize="10.5" fill="#070707" textAnchor="end">FORWARD-DEPLOYED ENGINEERS</text>
        <text x="516" y="524" fontSize="7.4" fill="#736f6a" textAnchor="end">ON SITE · IN PRODUCTION</text>
      </g>
    </svg>
  );
}
