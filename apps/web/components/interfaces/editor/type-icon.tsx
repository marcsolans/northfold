import {
  BarChart3,
  CalendarDays,
  CheckSquare,
  Gauge,
  List,
  type LucideIcon,
  MessageSquare,
  MousePointerClick,
  Table2,
  TextCursorInput,
  Upload,
} from "lucide-react";

import type { ComponentType } from "../types";

export const TYPE_ICONS: Record<ComponentType, LucideIcon> = {
  data_table: Table2,
  chart: BarChart3,
  kpi: Gauge,
  form: TextCursorInput,
  chat: MessageSquare,
  record_list: List,
  calendar: CalendarDays,
  file_upload: Upload,
  action_button: MousePointerClick,
  approvals_inbox: CheckSquare,
};

export function TypeIcon({ type, className }: { type: ComponentType; className?: string }) {
  const Icon = TYPE_ICONS[type];
  return <Icon className={className} aria-hidden />;
}
