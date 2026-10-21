import { HiOutlineInformationCircle } from "react-icons/hi2";

import { formatMoney } from "@/lib/money";
import type { CartChange } from "@/server/cart";

function describe(change: CartChange): string {
  switch (change.type) {
    case "removed":
      return change.reason === "sold_out"
        ? `${change.label} sold out and was removed.`
        : `${change.label} is no longer available and was removed.`;
    case "quantity_reduced":
      return `Only ${change.to} of ${change.label} available — quantity reduced from ${change.from}.`;
    case "price_changed":
      return `The price of ${change.label} changed from ${formatMoney(change.from)} to ${formatMoney(change.to)}.`;
  }
}

/** Tells the customer exactly what server re-validation changed in their bag. */
export function CartChanges({ changes }: { changes: CartChange[] }) {
  if (changes.length === 0) return null;
  return (
    <div
      role="status"
      className="flex gap-3 rounded-lg border border-warning/30 bg-warning-soft px-5 py-4 text-sm"
    >
      <HiOutlineInformationCircle
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-warning"
      />
      <div>
        <p className="font-medium text-foreground">We updated your bag</p>
        <ul className="mt-1 space-y-1 text-muted-foreground">
          {changes.map((change, index) => (
            <li key={index}>{describe(change)}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
