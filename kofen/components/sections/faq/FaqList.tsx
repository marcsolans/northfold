"use client";

import { useId, useState } from "react";

export type FaqItem = { question: string; answer: string };

/** Independent accordion items (several can be open at once). */
export function FaqList({ items }: { items: FaqItem[] }) {
  const [open, setOpen] = useState<boolean[]>(() => items.map(() => false));
  const uid = useId();
  return (
    <div className="min-w-0 flex-[2_1_560px] border-t border-stone">
      {items.map((it, i) => {
        const qid = `${uid}-q${i}`;
        const aid = `${uid}-a${i}`;
        return (
          <div key={it.question} className="border-b border-stone">
            <h3 className="m-0 text-lg font-normal leading-[1.35] tracking-[-0.015em]">
              <button
                id={qid}
                type="button"
                aria-expanded={open[i]}
                aria-controls={aid}
                onClick={() => setOpen((o) => o.map((v, j) => (j === i ? !v : v)))}
                className="faq-q flex min-h-11 w-full items-center gap-4 py-[22px] text-start"
              >
                <span aria-hidden="true" className="faq-bullet size-[5px] flex-none border border-obsidian" />
                <span className="flex-1">{it.question}</span>
                <span aria-hidden="true" className="faq-plus" />
              </button>
            </h3>
            <div id={aid} role="region" aria-labelledby={qid} className="faq-a" {...(open[i] ? { "data-open": "" } : {})}>
              <div>
                <p className="m-0 max-w-[40em] pb-[26px] ps-[21px] text-[15.5px] leading-[1.65] text-concrete">{it.answer}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
