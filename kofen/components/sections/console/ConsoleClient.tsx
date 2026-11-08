"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ArrowBox } from "@/components/ui/primitives";
import { pad2 } from "@/lib/text";
import {
  RESTING_T,
  SCENE_MS,
  T_DONE,
  TOTAL_MS,
  frameAt,
  frameKey,
  hintVisible,
  mmss,
  placeholderAt,
  type SceneFrame,
} from "./timeline";

export type Scenario = {
  label: string;
  from: string;
  subject: string;
  body: string;
  steps: string[];
  reply: string;
  fields: { label: string; value: string }[];
  waiting: string;
  done: string;
};

export type ConsoleCopy = {
  demoBadge: string;
  hint: string;
  group: string;
  agentsRunning: string;
  agentName: string;
  working: string;
  approve: string;
  play: string;
  pause: string;
  scenarios: Scenario[];
};

export type ComposerCopy = {
  label: string;
  placeholders: string[];
  chips: { label: string; text: string }[];
  send: string;
  note: string;
  emailSubject: string;
};

type Props = {
  copy: ConsoleCopy;
  composer: ComposerCopy;
  labels: { scenarios: string; timeline: string };
  email: string;
};

/** Systems that orbit the window at ≥1280px: [name, top, left, right] as in the prototype. */
const ORBIT: [string, string, string, string][] = [
  ["SAP", "8%", "-120px", "auto"],
  ["Outlook", "36%", "-132px", "auto"],
  ["Excel", "66%", "-104px", "auto"],
  ["WhatsApp", "14%", "auto", "-136px"],
  ["Sage", "46%", "auto", "-96px"],
  ["Twilio", "76%", "auto", "-118px"],
];

const mono = "font-mono uppercase";
const rise = { animation: "k-rise .4s var(--ease-out-soft) both" };

/**
 * The simulated product window. One requestAnimationFrame clock drives the
 * playhead; it only runs while the console is on screen and the tab is visible.
 * React re-renders only when the discrete frame changes (see frameKey); the
 * chapter bars, clock and placeholder typewriter are written straight to the DOM.
 */
export function ConsoleClient({ copy, composer, labels, email }: Props) {
  const { scenarios } = copy;
  const replyLengths = useMemo(() => scenarios.map((s) => Array.from(s.reply).length), [scenarios]);

  // Server render (and no-JS / reduced motion) shows scene 1 approved.
  const [frame, setFrame] = useState<SceneFrame>(() => frameAt(RESTING_T, replyLengths));
  const [playing, setPlaying] = useState(false);
  const [hint, setHint] = useState(false);
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const placeholderRef = useRef<HTMLSpanElement>(null);
  const clockRef = useRef<HTMLSpanElement>(null);
  const barRefs = useRef<Array<HTMLSpanElement | null>>([]);

  const t = useRef(RESTING_T);
  const clock = useRef(0);
  const playingRef = useRef(false);
  const hinted = useRef(false);
  const keyRef = useRef(frameKey(frame));
  const hintRef = useRef(false);
  const reduced = useRef(false);

  /** Push the playhead into React state (if the frame changed) and the DOM. */
  const sync = useCallback(() => {
    const f = frameAt(t.current, replyLengths);
    const key = frameKey(f);
    if (key !== keyRef.current) {
      keyRef.current = key;
      setFrame(f);
    }
    const h = hintVisible(clock.current, hinted.current);
    if (h !== hintRef.current) {
      hintRef.current = h;
      setHint(h);
    }
    barRefs.current.forEach((el, i) => {
      if (!el) return;
      const pct = i < f.scene ? 100 : i > f.scene ? 0 : (f.local / SCENE_MS) * 100;
      el.style.width = `${pct.toFixed(1)}%`;
    });
    if (clockRef.current) clockRef.current.textContent = `${mmss(t.current)} / ${mmss(TOTAL_MS)}`;
    if (placeholderRef.current && !reduced.current) {
      placeholderRef.current.textContent = placeholderAt(clock.current, composer.placeholders);
    }
  }, [replyLengths, composer.placeholders]);

  // Single rAF clock, paused off-screen and in hidden tabs.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduced.current) {
      t.current = 0;
      playingRef.current = true;
      setPlaying(true);
    }
    sync();

    let raf = 0;
    let last = 0;
    let visible = false;
    const step = (now: number) => {
      const dt = last ? Math.min(now - last, 250) : 0;
      last = now;
      clock.current += dt;
      if (playingRef.current) t.current = (t.current + dt) % TOTAL_MS;
      sync();
      raf = requestAnimationFrame(step);
    };
    const update = () => {
      const run = visible && !document.hidden;
      root.toggleAttribute("data-paused", !run);
      if (run && !raf) {
        last = 0;
        raf = requestAnimationFrame(step);
      } else if (!run && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    const io = new IntersectionObserver(
      ([e]) => {
        visible = e.isIntersecting;
        update();
      },
      { threshold: 0.15 },
    );
    io.observe(root);
    document.addEventListener("visibilitychange", update);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", update);
      cancelAnimationFrame(raf);
    };
  }, [sync]);

  const markHinted = () => {
    hinted.current = true;
  };
  const seek = (ms: number) => {
    t.current = ms;
    markHinted();
    sync();
  };
  const pickScene = (i: number) => {
    playingRef.current = true;
    setPlaying(true);
    seek(i * SCENE_MS);
  };
  const pickChapter = (i: number) => seek(i * SCENE_MS);
  const approve = () => {
    const start = Math.floor(t.current / SCENE_MS) * SCENE_MS;
    if (t.current - start < T_DONE) t.current = start + T_DONE;
    markHinted();
    sync();
  };
  const togglePlay = () => {
    playingRef.current = !playingRef.current;
    setPlaying(playingRef.current);
  };

  const mailHref = `mailto:${email}?subject=${encodeURIComponent(composer.emailSubject)}${
    q.trim() ? `&body=${encodeURIComponent(q.trim())}` : ""
  }`;
  const addChip = (text: string) => {
    setQ((cur) => (cur.includes(text) ? cur : cur.trim() ? `${cur.trim()} ${text}` : text));
    inputRef.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      window.location.href = mailHref;
    }
  };

  const scene = scenarios[frame.scene];

  return (
    <div
      ref={rootRef}
      className="console-frame relative border border-[var(--line)] bg-hull px-[clamp(12px,7vw,160px)] py-[clamp(16px,5vw,72px)]"
      style={{
        backgroundImage: "radial-gradient(rgba(115,111,106,0.35) 1px, transparent 1.2px)",
        backgroundSize: "16px 16px",
      }}
    >
      {/* Orbiting-light system chips (≥1280px) */}
      <div
        aria-hidden="true"
        dir="ltr"
        className="pointer-events-none absolute inset-x-[clamp(12px,7vw,160px)] inset-y-[clamp(16px,5vw,72px)] hidden xl:block"
      >
        {ORBIT.map(([name, top, left, right], i) => (
          <span
            key={name}
            className="absolute overflow-hidden p-px"
            style={{ top, left, right, background: "rgba(184,174,164,0.6)", "--kd": `${i * -1370}ms` } as React.CSSProperties}
          >
            <span className="kspin" />
            <span className={`relative flex h-10 items-center bg-white px-3.5 text-[11px] tracking-[0.04em] text-carbon ${mono}`}>
              {name}
            </span>
          </span>
        ))}
      </div>

      <div
        id="try"
        role="group"
        aria-label={`${copy.group} · ${copy.demoBadge}`}
        className="relative scroll-mt-[140px] border border-stone bg-white text-start shadow-window"
      >
        {/* Title bar */}
        <div className="flex h-11 items-center gap-3.5 border-b border-[var(--line-60)] bg-signal px-3.5">
          <span className={`flex min-w-0 items-center gap-2 overflow-hidden whitespace-nowrap text-[11px] tracking-[0.04em] text-concrete-deep ${mono}`}>
            {copy.group} <span aria-hidden="true">/</span> <span className="text-obsidian">{scene.label}</span>
          </span>
          <div className="flex-1" />
          <span className={`hidden flex-none text-[10px] tracking-[0.08em] text-concrete-deep md:inline ${mono}`}>{copy.demoBadge}</span>
          <span
            className={`inline-flex flex-none items-center gap-2 whitespace-nowrap border border-stone px-2 py-1 text-[10px] tracking-[0.08em] text-carbon ${mono}`}
          >
            <span aria-hidden="true" className="blink-sq size-1.5 bg-success" />
            {copy.agentsRunning}
          </span>
        </div>

        <div className="flex flex-col lg:flex-row">
          {/* Sidebar: scenarios */}
          <div
            role="group"
            aria-label={labels.scenarios}
            className="flex min-w-0 flex-col gap-1 border-b border-[var(--line-60)] px-2.5 py-3.5 lg:w-[200px] lg:flex-none lg:border-b-0 lg:border-e"
          >
            {scenarios.map((s, i) => {
              const active = i === frame.scene;
              return (
                <button
                  key={s.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => pickScene(i)}
                  className={`flex min-h-11 items-center gap-2.5 px-3 text-start text-sm transition-colors duration-200 hover:bg-signal ${
                    active ? "bg-signal text-obsidian" : "bg-transparent text-concrete"
                  }`}
                >
                  <span aria-hidden="true" className={`size-1.5 flex-none transition-colors duration-200 ${active ? "bg-rust" : "bg-hairline"}`} />
                  <span>{s.label}</span>
                </button>
              );
            })}
            <span
              aria-hidden={!hint}
              className={`mx-3 mt-2 self-start bg-obsidian px-[9px] py-[5px] text-[10px] tracking-[0.08em] text-white ${mono} ${
                hint ? "visible animate-[k-pop_.35s_var(--ease-out-soft)_both]" : "invisible"
              }`}
            >
              {copy.hint}
            </span>
          </div>

          {/* Main column */}
          <div className="flex min-w-0 flex-1 flex-col">
            {/* Timeline. Invisible final states of every scene share the cell, so its height never changes. */}
            <div aria-live="off" className="grid min-h-[500px] flex-1 px-[clamp(16px,2.4vw,32px)] py-6">
              {scenarios.map((s, i) => (
                <div key={i} aria-hidden="true" className="invisible [grid-area:1/1]">
                  <TimelineView
                    scenario={s}
                    frame={frameAt(i * SCENE_MS + RESTING_T, replyLengths)}
                    copy={copy}
                    ghost
                  />
                </div>
              ))}
              <div className="[grid-area:1/1]">
                <TimelineView scenario={scene} frame={frame} copy={copy} onApprove={approve} />
              </div>
            </div>

            {/* Composer */}
            <div className="flex flex-col gap-2.5 border-t border-[var(--line-60)] px-[clamp(16px,2.4vw,24px)] pb-3 pt-3.5">
              <label htmlFor="console-q" className="sr-only">
                {composer.label}
              </label>
              <div className="inline-form">
                <div className="relative min-w-0 sm:flex-1">
                  <input
                    ref={inputRef}
                    id="console-q"
                    type="text"
                    autoComplete="off"
                    enterKeyHint="send"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    onKeyDown={onKey}
                    className="h-[46px] w-full border border-stone bg-white px-3.5 text-sm text-obsidian outline-none focus-visible:border-obsidian"
                  />
                  {!q && !focused && (
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute start-[15px] top-1/2 max-w-[calc(100%-30px)] -translate-y-1/2 overflow-hidden whitespace-nowrap text-sm text-concrete"
                    >
                      <span ref={placeholderRef}>{composer.placeholders[0]}</span>
                      <span className="animate-[k-blink_1s_steps(1)_infinite] text-rust">|</span>
                    </span>
                  )}
                </div>
                <a href={mailHref} className="btn">
                  {composer.send}
                  <ArrowBox />
                </a>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {composer.chips.map((c) => {
                  const used = q.includes(c.text);
                  return (
                    <button
                      key={c.label}
                      type="button"
                      aria-pressed={used}
                      onClick={() => addChip(c.text)}
                      className={`chip min-h-11 border px-3 text-xs transition-colors duration-200 ${
                        used ? "border-obsidian bg-obsidian text-white" : "border-stone bg-white text-carbon"
                      }`}
                    >
                      <span aria-hidden="true">{used ? "✓" : "+"}</span> {c.label}
                    </button>
                  );
                })}
              </div>
              <span className={`text-[10px] tracking-[0.06em] text-concrete ${mono}`}>{composer.note}</span>
            </div>

            {/* Player */}
            <div className="flex items-center gap-3.5 border-t border-[var(--line-60)] px-[clamp(12px,2vw,20px)] py-1">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={playing ? copy.pause : copy.play}
                className="flex size-11 flex-none items-center justify-center border border-stone bg-white text-obsidian"
              >
                {playing ? (
                  <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="5" y="4" width="5" height="16" />
                    <rect x="14" y="4" width="5" height="16" />
                  </svg>
                ) : (
                  <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M6 4v16l14-8z" />
                  </svg>
                )}
              </button>
              <div role="group" aria-label={labels.timeline} className="flex min-w-0 flex-1 gap-1.5">
                {scenarios.map((s, i) => (
                  <button
                    key={s.label}
                    type="button"
                    aria-current={i === frame.scene ? "step" : undefined}
                    onClick={() => pickChapter(i)}
                    className={`flex min-h-11 min-w-0 flex-1 flex-col justify-center gap-[7px] bg-transparent py-1.5 text-start text-[10px] tracking-[0.06em] ${mono} ${
                      i === frame.scene ? "text-obsidian" : "text-concrete"
                    }`}
                  >
                    <span aria-hidden="true" className="block h-0.5 overflow-hidden bg-hairline">
                      <span
                        ref={(el) => {
                          barRefs.current[i] = el;
                        }}
                        className="block h-0.5 bg-rust"
                        style={{ width: i < frame.scene ? "100%" : i > frame.scene ? "0%" : `${((RESTING_T / SCENE_MS) * 100).toFixed(1)}%` }}
                      />
                    </span>
                    <span className="overflow-hidden text-ellipsis whitespace-nowrap">
                      {pad2(i + 1)} {s.label}
                    </span>
                  </button>
                ))}
              </div>
              <span ref={clockRef} dir="ltr" aria-hidden="true" className="flex-none font-mono text-[10px] tabular-nums text-concrete">
                {`${mmss(RESTING_T)} / ${mmss(TOTAL_MS)}`}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Check() {
  return (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#027a48" strokeWidth="2" strokeLinecap="square" className="flex-none">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="m-0.5 size-2.5 flex-none animate-[k-spin_.8s_linear_infinite] border-[1.5px] border-hairline border-t-rust-deep"
      style={{ borderRadius: "50%" }}
    />
  );
}

/** Source message → agent block (steps, typed reply, result card). `ghost` renders a static, inert copy for sizing. */
function TimelineView({
  scenario: s,
  frame: f,
  copy,
  ghost = false,
  onApprove,
}: {
  scenario: Scenario;
  frame: SceneFrame;
  copy: ConsoleCopy;
  ghost?: boolean;
  onApprove?: () => void;
}) {
  const anim = ghost ? undefined : rise;
  const typed = ghost ? s.reply : Array.from(s.reply).slice(0, f.typedChars).join("");
  return (
    <div className="flex flex-col gap-4">
      {f.showSource && (
        <div style={anim} className="flex max-w-[min(560px,100%)] flex-col gap-1.5 self-end border border-[var(--line-60)] bg-signal px-4 py-3.5">
          <div className={`flex flex-wrap justify-between gap-3 text-[10px] tracking-[0.04em] text-concrete-deep ${mono}`}>
            <span dir="ltr">{s.from}</span>
            <span>{s.subject}</span>
          </div>
          <p className="m-0 text-sm leading-[1.55] text-carbon">{s.body}</p>
        </div>
      )}
      {f.showAgent && (
        <div style={anim} className="flex items-start gap-3">
          <span aria-hidden="true" className="flex size-7 flex-none items-center justify-center bg-obsidian text-sm tracking-[-0.05em] text-white">
            K
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-2.5">
            <div className={`flex items-center gap-2.5 text-[10px] tracking-[0.08em] text-concrete ${mono}`}>
              <span className="text-obsidian">{copy.agentName}</span>
              {f.working && (
                <span className="inline-flex items-center gap-2">
                  {copy.working}
                  <span aria-hidden="true" className="inline-flex gap-[3px]">
                    {[0, 0.15, 0.3].map((d) => (
                      <span key={d} className="size-[3px] bg-obsidian" style={{ animation: `k-dot 1s ${d}s infinite` }} />
                    ))}
                  </span>
                </span>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              {s.steps.map((text, i) =>
                f.steps[i] === "hidden" ? null : (
                  <div key={i} style={ghost ? undefined : { animation: "k-rise .35s var(--ease-out-soft) both" }} className="flex items-center gap-2.5">
                    {f.steps[i] === "done" ? <Check /> : <Spinner />}
                    <span className="font-mono text-xs leading-[1.4] tracking-normal text-carbon">{text}</span>
                  </div>
                ),
              )}
            </div>
            {f.showReply && (
              <p className="m-0 max-w-[40em] text-[15.5px] leading-[1.6] text-obsidian">
                {typed}
                {f.typing && (
                  <span
                    aria-hidden="true"
                    className="ms-0.5 inline-block h-[1em] w-[7px] animate-[k-blink_1s_steps(1)_infinite] bg-rust align-[-2px]"
                  />
                )}
              </p>
            )}
            {f.showCard && (
              <div
                style={ghost ? undefined : { animation: "k-pop .42s var(--ease-out-soft) both" }}
                className="@container flex flex-col border border-stone bg-white"
              >
                <dl className="m-0 grid grid-cols-1 gap-px bg-[var(--line-60)] @[18rem]:grid-cols-2 @[36rem]:grid-cols-4">
                  {s.fields.map((field) => (
                    <div key={field.label} className="flex min-w-0 flex-col gap-1.5 bg-white px-4 py-3.5">
                      <dt className={`text-[10px] tracking-[0.08em] text-concrete ${mono}`}>{field.label}</dt>
                      <dd className="m-0 text-lg tracking-[-0.02em] text-obsidian [overflow-wrap:anywhere]">{field.value}</dd>
                    </div>
                  ))}
                </dl>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--line-60)] py-2.5 pe-3 ps-4">
                  <span
                    className={`inline-flex items-center gap-2 text-[10px] tracking-[0.08em] ${mono} ${
                      f.done ? "text-success-strong" : "text-rust-ink"
                    }`}
                  >
                    <span aria-hidden="true" className={`size-1.5 ${f.done ? "bg-success" : "bg-rust"}`} />
                    {f.done ? s.done : s.waiting}
                  </span>
                  {ghost ? (
                    <span className="btn">{`✓ ${copy.approve}`}</span>
                  ) : (
                    <button
                      type="button"
                      onClick={onApprove}
                      disabled={f.done}
                      className={`btn ${f.done ? "!bg-signal !text-concrete-deep" : ""}`}
                    >
                      {f.done ? `✓ ${copy.approve}` : copy.approve}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
