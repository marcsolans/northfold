import { heroLines, heroTiles } from "@/lib/lattice";

/** Animated SVG lattice behind the hero: 3 scenes on an 18s loop (CSS keyframes in globals.css). */
export function HeroLattice() {
  return (
    <div className="khgroot" aria-hidden="true" data-hero-lattice="">
      <svg viewBox="0 0 1200 800" preserveAspectRatio="xMinYMin slice" className="block size-full">
        <g fill="none" stroke="#070707" strokeWidth="0.6" strokeOpacity="0.16">
          {heroLines.map((l, i) => (
            <path
              key={i}
              d={l.d}
              className={`khg khg-${l.scene}`}
              style={{ "--L": l.L, "--d": `${l.delay}s` } as React.CSSProperties}
            />
          ))}
        </g>
        <g className="khtiles">
          {heroTiles.map((t, i) => (
            <rect
              key={i}
              x={t.x}
              y={t.y}
              width="100"
              height="100"
              fill={t.fill}
              className={`khp khp-${t.scene}`}
              style={{ "--d": `${t.delay}s` } as React.CSSProperties}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}
