/** Types and query keys for GET/PATCH /api/v1/onboarding and GET /api/v1/onboarding/checklist (contracts §6). */

export type StepKey = "describe" | "template" | "data" | "test" | "deploy";
export const WIZARD_STEPS = ["describe", "template", "data", "test"] as const satisfies readonly StepKey[];
export type WizardStep = (typeof WIZARD_STEPS)[number];

export const USE_CASES = [
  "customer_support",
  "lead_qualification",
  "document_extraction",
  "internal_assistant",
  "contract_analysis",
  "operations",
  "voice_reception",
  "reporting",
  "other",
] as const;
export type UseCase = (typeof USE_CASES)[number];

export interface ChecklistStep {
  key: StepKey;
  done: boolean;
  href: string;
}

export interface Checklist {
  steps: ChecklistStep[];
  complete: boolean;
  dismissed: boolean;
}

export interface OnboardingState extends Checklist {
  goal: string | null;
  use_case: UseCase | null;
  skipped_steps: StepKey[];
  completed_at: string | null;
  updated_at: string | null;
  project: { id: string; name: string } | null;
  agent: { id: string; name: string; project_id: string } | null;
}

export interface OnboardingPatch {
  goal?: string | null;
  use_case?: UseCase | null;
  skipped_steps?: StepKey[];
  dismissed?: boolean;
  completed?: boolean;
}

export const ONBOARDING_KEY = ["onboarding"] as const;
export const CHECKLIST_KEY = ["onboarding", "checklist"] as const;

export function isWizardStep(value: string | null): value is WizardStep {
  return value !== null && (WIZARD_STEPS as readonly string[]).includes(value);
}
