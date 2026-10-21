"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatMoney } from "@/lib/money";

const shortDate = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

function label(date: string): string {
  return shortDate.format(new Date(`${date}T00:00:00Z`));
}

/** Daily revenue from paid orders over the last 30 days. */
export function RevenueChart({ data }: { data: { date: string; revenue: number }[] }) {
  const total = data.reduce((sum, point) => sum + point.revenue, 0);
  return (
    <figure>
      <div className="h-64 w-full" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 20, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.25} />
                <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={label}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
              tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(value: number) => formatMoney(value, { whole: true })}
              tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            />
            <Tooltip
              labelFormatter={(value) => label(String(value))}
              formatter={(value) => [formatMoney(Number(value)), "Revenue"]}
              contentStyle={{ borderRadius: 6, borderColor: "var(--color-border)", fontSize: 12 }}
            />
            <Area
              type="monotone"
              dataKey="revenue"
              stroke="var(--color-accent)"
              strokeWidth={2}
              fill="url(#revenueFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">
        Revenue over the last 30 days: {formatMoney(total)} in total.
      </figcaption>
    </figure>
  );
}
