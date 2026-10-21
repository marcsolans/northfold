"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { Search } from "lucide-react";
import * as React from "react";

export interface CommandItem {
  id: string;
  label: string;
  group: string;
  icon?: React.ReactNode;
  keywords?: string[];
  shortcut?: string;
  onSelect: () => void;
}

/** ⌘K command palette. */
export function CommandPalette({
  open,
  onOpenChange,
  items,
  placeholder = "Buscar o saltar a…",
  emptyLabel = "Sin resultados",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: CommandItem[];
  placeholder?: string;
  emptyLabel?: string;
}) {
  const groups = React.useMemo(() => {
    const map = new Map<string, CommandItem[]>();
    for (const item of items) {
      const list = map.get(item.group) ?? [];
      list.push(item);
      map.set(item.group, list);
    }
    return [...map.entries()];
  }, [items]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <DialogPrimitive.Content className="fixed left-1/2 top-[15vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-md border border-border bg-surface shadow-2xl">
          <DialogPrimitive.Title className="sr-only">{placeholder}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">{placeholder}</DialogPrimitive.Description>
          <Command loop className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="size-4 text-fg-subtle" />
              <Command.Input
                autoFocus
                placeholder={placeholder}
                className="h-11 w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
              />
            </div>
            <Command.List className="max-h-96 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-subtle">{emptyLabel}</Command.Empty>
              {groups.map(([group, list]) => (
                <Command.Group
                  key={group}
                  heading={group}
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-fg-subtle"
                >
                  {list.map((item) => (
                    <Command.Item
                      key={item.id}
                      value={`${item.label} ${(item.keywords ?? []).join(" ")}`}
                      onSelect={() => {
                        onOpenChange(false);
                        item.onSelect();
                      }}
                      className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-2 text-sm text-fg data-[selected=true]:bg-subtle [&_svg]:size-4 [&_svg]:text-fg-subtle"
                    >
                      {item.icon}
                      <span className="flex-1">{item.label}</span>
                      {item.shortcut ? <span className="text-xs text-fg-subtle">{item.shortcut}</span> : null}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
