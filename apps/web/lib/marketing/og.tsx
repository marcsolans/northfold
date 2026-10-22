import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 };

/** Sober Open Graph card: white background, 1px rule, red mark, title. Uses next/og's bundled font. */
export function ogImage({ eyebrow, title, footer }: { eyebrow: string; title: string; footer: string }): ImageResponse {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#ffffff",
          color: "#111111",
          padding: "72px 80px",
          borderBottom: "12px solid #D52B1E",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <svg width="44" height="44" viewBox="0 0 16 16">
            <rect width="16" height="16" rx="2" fill="#D52B1E" />
            <path d="M3.5 12.5 10.5 3.5h2l-7 9z" fill="#fff" />
          </svg>
          <span style={{ fontSize: 40, letterSpacing: -1 }}>Messer</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <span style={{ fontSize: 26, color: "#D52B1E", textTransform: "uppercase", letterSpacing: 2 }}>{eyebrow}</span>
          <span style={{ fontSize: title.length > 70 ? 54 : 64, lineHeight: 1.1, letterSpacing: -1.5, maxWidth: 1040 }}>
            {title}
          </span>
        </div>
        <div style={{ display: "flex", fontSize: 24, color: "#57534e", borderTop: "1px solid #e7e5e1", paddingTop: 24 }}>
          {footer}
        </div>
      </div>
    ),
    OG_SIZE,
  );
}
