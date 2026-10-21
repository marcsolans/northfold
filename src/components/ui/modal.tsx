"use client";

import { type ReactNode, useEffect, useId, useRef } from "react";
import { HiXMark } from "react-icons/hi2";

import { cn } from "@/lib/utils";

/**
 * Accessible modal built on the native <dialog>: `showModal()` gives focus trapping, inert
 * background, Escape to close and focus restoration for free.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onClose={onClose}
      onClick={(event) => {
        // A click on the backdrop targets the <dialog> element itself.
        if (event.target === event.currentTarget) onClose();
      }}
      className={cn(
        "m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg border border-border bg-card p-0 text-foreground shadow-xl backdrop:bg-foreground/40 backdrop:backdrop-blur-[2px] open:animate-fade-in",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
        <div>
          <h2 id={titleId} className="text-base font-medium tracking-tight">
            {title}
          </h2>
          {description ? (
            <p id={descriptionId} className="mt-1 text-sm text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="-m-1 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Close dialog"
        >
          <HiXMark aria-hidden="true" className="size-5" />
        </button>
      </div>
      {children ? <div className="px-6 py-5">{children}</div> : null}
      {footer ? (
        <div className="flex flex-col-reverse gap-2 border-t border-border px-6 py-4 sm:flex-row sm:justify-end">
          {footer}
        </div>
      ) : null}
    </dialog>
  );
}
