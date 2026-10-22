/**
 * Billing UI shared with every area. When an API call answers 402 (``plan_limit`` or ``read_only``):
 *
 *   const upgrade = useUpgradeDialog();
 *   useMutation({ ..., onError: (err) => { if (!upgrade.handle(err)) toast.error(String(err)); } });
 *   return <>{...}{upgrade.dialog}</>;
 *
 * or render ``<PlanLimitNotice error={mutation.error} />`` inline next to the form.
 */
export { PlanLimitNotice } from "./plan-limit-notice";
export {
  UpgradeDialog,
  billingHref,
  isPlanLimitError,
  planLimitInfo,
  useUpgradeDialog,
  type PlanLimitDetails,
  type PlanLimitInfo,
} from "./upgrade-dialog";
export { UsageMeter } from "./usage-meter";
export { IntervalToggle, PlanGrid, TestModeBadge, type PlanAction } from "./plan-grid";
export { STATE_TONES, errorText, formatUtcDate, inclusiveEnd, useFollowCheckout } from "./hooks";
export * from "./types";
