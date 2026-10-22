"use client";

/** Translated labels for the @messer/ui data components (packages/ui never hardcodes copy). */

import type {
  ApprovalsInboxLabels,
  CalendarLabels,
  ChatPanelLabels,
  DataChartLabels,
  DataFormLabels,
  DataStateLabels,
  DataTableLabels,
  FileDropzoneLabels,
  RecordListLabels,
} from "@messer/ui";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { localeTag } from "@/lib/format";

export interface DataLabels {
  locale: string;
  state: DataStateLabels;
  table: DataTableLabels;
  chart: DataChartLabels;
  kpi: DataStateLabels & { increase: string; decrease: string };
  form: DataFormLabels;
  chat: ChatPanelLabels;
  list: RecordListLabels;
  calendar: CalendarLabels;
  upload: FileDropzoneLabels;
  approvals: ApprovalsInboxLabels;
  filters: { search: string; all: string };
  action: { confirmTitle: string; confirm: string; cancel: string };
}

export function useDataLabels(): DataLabels {
  const t = useTranslations("interfaces.data");
  const locale = localeTag(useLocale());
  return React.useMemo(() => {
    const state: DataStateLabels = {
      loading: t("loading"),
      empty: t("empty"),
      errorTitle: t("errorTitle"),
      retry: t("retry"),
    };
    const paging = {
      previous: t("previous"),
      next: t("next"),
      page: (page: number, pages: number) => t("page", { page, pages }),
    };
    return {
      locale,
      state,
      table: {
        ...state,
        ...paging,
        search: t("search"),
        rows: (count: number) => t("rows", { count }),
        sortBy: (column: string) => t("sortBy", { column }),
        truncated: t("truncated"),
      },
      chart: { ...state, table: t("chartTable"), other: t("other") },
      kpi: { ...state, increase: t("increase"), decrease: t("decrease") },
      form: {
        submit: t("submit"),
        submitting: t("submitting"),
        required: t("required"),
        invalidEmail: t("invalidEmail"),
        invalidNumber: t("invalidNumber"),
        min: (n: number) => t("min", { n }),
        max: (n: number) => t("max", { n }),
        select: t("selectOption"),
        again: t("sendAnother"),
      },
      chat: {
        placeholder: t("chatPlaceholder"),
        send: t("send"),
        stop: t("stop"),
        reset: t("newConversation"),
        working: t("working"),
        approvalPending: t("approvalPending"),
        messages: t("messages"),
        loading: t("loading"),
      },
      list: { ...state, ...paging, search: t("search") },
      calendar: {
        ...state,
        previous: t("previousMonth"),
        next: t("nextMonth"),
        today: t("today"),
        more: (count: number) => t("more", { count }),
      },
      upload: {
        drop: t("drop"),
        browse: t("browse"),
        limits: (accept: string, maxMb: number) => (accept ? t("limits", { accept, maxMb }) : t("limitsAny", { maxMb })),
        tooLarge: (maxMb: number) => t("tooLarge", { maxMb }),
        unsupported: t("unsupported"),
        uploading: t("uploading"),
        done: t("uploaded"),
        failed: t("uploadFailed"),
      },
      approvals: {
        ...state,
        empty: t("noApprovals"),
        approve: t("approve"),
        deny: t("deny"),
        approveTitle: t("approveTitle"),
        denyTitle: t("denyTitle"),
        comment: t("comment"),
        cancel: t("cancel"),
        status: (status: string) =>
          ["pending", "approved", "denied", "expired"].includes(status) ? t(`approvalStatus.${status}`) : status,
        expires: (when: string) => t("expires", { when }),
        noPermission: t("noPermission"),
      },
      filters: { search: t("search"), all: t("all") },
      action: { confirmTitle: t("confirmTitle"), confirm: t("confirm"), cancel: t("cancel") },
    };
  }, [t, locale]);
}
