import { ImageResponse } from "next/og";

export const ogSize = { width: 1200, height: 630 };

/**
 * Fetch a Google Font subset (only the glyphs in `text`) as TTF for next/og.
 * Runs at build time; returns null if the network is unavailable.
 */
async function googleFont(family: string, text: string, weight = 400): Promise<ArrayBuffer | null> {
  "use cache";
  try {
    const api = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family)}:wght@${weight}&text=${encodeURIComponent(text)}`;
    const css = await (await fetch(api, { signal: AbortSignal.timeout(8000) })).text();
    const url = css.match(/src: url\((.+?)\) format\('(?:opentype|truetype)'\)/)?.[1];
    if (!url) return null;
    return await (await fetch(url, { signal: AbortSignal.timeout(8000) })).arrayBuffer();
  } catch {
    return null;
  }
}

/** Black square + "Kofen" + headline on the hero gradient. */
export async function renderOgImage({ headline, script }: { headline: string; script?: "zh" }) {
  const text = `Kofen${headline}KOFEN BARCELONA / SAN FRANCISCO`;
  const [geist, mono, sc] = await Promise.all([
    googleFont("Geist", text),
    googleFont("Geist Mono", "BARCELONA / SAN FRANCISCO"),
    script === "zh" ? googleFont("Noto Sans SC", headline) : Promise.resolve(null),
  ]);
  const fonts = [
    geist && { name: "Geist", data: geist, weight: 400 as const, style: "normal" as const },
    mono && { name: "Geist Mono", data: mono, weight: 400 as const, style: "normal" as const },
    sc && { name: "Noto Sans SC", data: sc, weight: 400 as const, style: "normal" as const },
  ].filter((f): f is NonNullable<typeof f> => Boolean(f));

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "64px 72px",
          background: "linear-gradient(98deg, #dedad5 0%, #f2f0ee 48%, #ffffff 100%)",
          color: "#070707",
          fontFamily: "Geist, 'Noto Sans SC'",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 26, height: 26, background: "#070707" }} />
          <div style={{ fontSize: 56, letterSpacing: "-0.05em" }}>Kofen</div>
        </div>
        <div style={{ display: "flex", fontSize: 88, lineHeight: 1.04, letterSpacing: "-0.05em", maxWidth: 960 }}>{headline}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, fontFamily: "'Geist Mono'", fontSize: 20, letterSpacing: "0.04em", color: "#736f6a" }}>
          <div style={{ width: 10, height: 10, background: "#d59566" }} />
          BARCELONA / SAN FRANCISCO
        </div>
      </div>
    ),
    { ...ogSize, fonts: fonts.length ? fonts : undefined },
  );
}
