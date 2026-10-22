"use client";

import { cn } from "@messer/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { DocNavSection } from "@/lib/content/docs";

/** Documentation sidebar; marks the current page. */
export function DocsNav({ sections, label }: { sections: DocNavSection[]; label: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label={label} className="flex flex-col gap-6">
      {sections.map((section) => (
        <div key={section.title}>
          <p className="px-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">{section.title}</p>
          <ul className="mt-2 flex flex-col gap-px">
            {section.pages.map((page) => {
              const active = pathname === page.href;
              return (
                <li key={page.href}>
                  <Link
                    href={page.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "block rounded-md px-2 py-1.5 text-sm transition-colors",
                      active ? "bg-subtle font-medium text-fg" : "text-fg-muted hover:bg-subtle hover:text-fg",
                    )}
                  >
                    {page.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
