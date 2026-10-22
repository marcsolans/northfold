// Data components for generated apps and dashboards (interfaces). Every label comes from the caller.
export { ActionButton, type ActionOutcome } from "./action-button";
export { ApprovalsInbox, type ApprovalItem, type ApprovalsInboxLabels } from "./approvals-inbox";
export { CalendarView, type CalendarLabels } from "./calendar";
export { ChatPanel, type ChatPanelLabels, type ChatPanelMessage } from "./chat-panel";
export { DataChart, type ChartKind, type ChartValueFormat, type DataChartLabels } from "./chart";
export {
  DataForm,
  type DataFormField,
  type DataFormLabels,
  type DataFormResult,
  type DataFormValues,
} from "./data-form";
export { DataPanel, DataStatus, type DataStateLabels } from "./data-state";
export { DataTable, type DataTableColumn, type DataTableLabels, type DataTableRowAction } from "./data-table";
export { FileDropzone, type FileDropzoneLabels, type UploadOutcome } from "./file-upload";
export { FilterBar, type FilterDef, type FilterOption, type FilterValues } from "./filter-bar";
export {
  type DataRow,
  type FormatOptions,
  type ValueFormat,
  columnsOf,
  formatValue,
  humanize,
  isNumericColumn,
  toNumber,
} from "./format";
export { KpiCard, type KpiCardProps } from "./kpi";
export { RecordList, type RecordListLabels } from "./record-list";
