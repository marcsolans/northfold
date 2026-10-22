"""The Composer's structured plan: what the architect proposes and the builders build (spec 7.7).

A plan describes the product, never the implementation details: agents and what they do, workflows with their
triggers and approval rules, knowledge bases (documents the customer will provide, tables), connectors, an interface
only when it is justified, channels, acceptance evals and risks. Templates ship the plan they implement
(``packages/templates/<id>/plan.json``) so the Composer can start from them.

``Plan.model_json_schema()`` is given to the architect model; ``validate_plan`` returns precise, human-readable
issues (used to ask the model for a repair and to show the user what is wrong).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, ValidationError, model_validator

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

BuiltinTool = Literal[
    "knowledge_search",
    "sql_query",
    "read_url",
    "web_search",
    "calculator",
    "current_datetime",
    "http_request",
    "send_email",
]
TriggerKind = Literal["manual", "cron", "webhook", "email", "file", "connector_event"]
StepKind = Literal[
    "input",
    "agent",
    "llm",
    "tool",
    "connector_action",
    "knowledge_search",
    "sql_query",
    "http_request",
    "condition",
    "loop",
    "transform",
    "approval",
    "wait",
    "sub_workflow",
    "output",
]
ChannelProvider = Literal["whatsapp", "slack", "teams", "email", "telegram", "phone", "web"]
Role = Literal["owner", "admin", "builder", "viewer"]


def _ident(value: str) -> str:
    if not IDENT.match(value):
        raise ValueError("usa minúsculas, números y guiones bajos, empezando por letra (máx. 63)")
    return value


Ident = Annotated[str, AfterValidator(_ident)]


class ApprovalRule(BaseModel):
    """A human approval before an action runs (e.g. credit notes over 500 €)."""

    action: str = Field(description="Tool or step that needs approval, e.g. 'issue_credit_note'")
    condition: str = Field(default="", description="When it applies, in plain words, e.g. 'importe > 500 €'")
    threshold: float | None = Field(default=None, description="Numeric threshold when the rule is an amount")
    field: str | None = Field(default=None, description="Input field the threshold applies to, e.g. 'amount'")
    approver_role: Role = "admin"


class PlanTable(BaseModel):
    name: Ident
    description: str = ""
    columns: list[dict[str, str]] = Field(
        default_factory=list, description='[{"name": "...", "type": "text|integer|numeric|boolean|date|timestamp"}]'
    )


class PlanKnowledgeBase(BaseModel):
    name: Ident
    title: str
    description: str = ""
    documents: list[str] = Field(default_factory=list, description="Documents the customer will upload (described)")
    tables: list[PlanTable] = Field(default_factory=list)


class PlanAgent(BaseModel):
    name: Ident
    title: str
    description: str
    instructions: str = Field(description="What the agent must do and how it behaves (becomes its system prompt)")
    tools: list[BuiltinTool] = Field(default_factory=list)
    connector_actions: list[str] = Field(default_factory=list, description="'<connector>.<action>' entries")
    knowledge: list[str] = Field(default_factory=list, description="Names of plan knowledge bases it uses")
    approvals: list[ApprovalRule] = Field(default_factory=list)
    voice: bool = False
    greeting: str = ""
    model_tier: Literal["fast", "standard", "powerful"] = "standard"


class PlanTrigger(BaseModel):
    kind: TriggerKind = "manual"
    schedule: str | None = Field(default=None, description="5-field cron for kind=cron")
    timezone: str = "Europe/Madrid"
    description: str = ""


class PlanStep(BaseModel):
    id: Ident
    kind: StepKind
    title: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class PlanWorkflow(BaseModel):
    name: Ident
    title: str
    description: str
    trigger: PlanTrigger = Field(default_factory=PlanTrigger)
    steps: list[PlanStep] = Field(default_factory=list)
    approvals: list[ApprovalRule] = Field(default_factory=list)


class PlanConnector(BaseModel):
    key: str = Field(description="Connector catalog key, e.g. 'google_drive', 'hubspot', 'postgres'")
    purpose: str
    required: bool = False


class PlanComponent(BaseModel):
    type: Literal[
        "data_table",
        "chart",
        "kpi",
        "form",
        "chat",
        "record_list",
        "calendar",
        "file_upload",
        "action_button",
        "approvals_inbox",
    ]
    title: str
    source: str = Field(default="", description="'kb:<name>.<table>', 'agent:<name>', 'workflow:<name>' or 'approvals'")
    description: str = ""


class PlanScreen(BaseModel):
    title: str
    components: list[PlanComponent] = Field(default_factory=list)


class PlanInterface(BaseModel):
    kind: Literal["app", "chat"] = "app"
    title: str
    justification: str = Field(description="Why the product needs an interface (the default is none)")
    screens: list[PlanScreen] = Field(default_factory=list)


class PlanChannel(BaseModel):
    provider: ChannelProvider
    agent: str
    purpose: str = ""


class PlanEval(BaseModel):
    member: str = Field(description="Agent or workflow name")
    name: Ident
    input: dict[str, Any] = Field(description='e.g. {"prompt": "..."} for agents')
    expect: Literal["contains", "not_contains", "tool_called", "approval_required", "min_length", "rubric"] = "contains"
    value: str = ""


class Plan(BaseModel):
    version: Literal[1] = 1
    goal: str
    summary: str
    template_id: str | None = None
    agents: list[PlanAgent] = Field(default_factory=list)
    workflows: list[PlanWorkflow] = Field(default_factory=list)
    knowledge_bases: list[PlanKnowledgeBase] = Field(default_factory=list)
    connectors: list[PlanConnector] = Field(default_factory=list)
    interface: PlanInterface | None = None
    channels: list[PlanChannel] = Field(default_factory=list)
    evals: list[PlanEval] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> Plan:
        issues = cross_reference_issues(self)
        if issues:
            raise ValueError("; ".join(issues))
        return self


def cross_reference_issues(plan: Plan) -> list[str]:
    issues: list[str] = []
    members = [a.name for a in plan.agents] + [w.name for w in plan.workflows]
    dupes = {m for m in members if members.count(m) > 1}
    if dupes:
        issues.append(f"nombres repetidos: {', '.join(sorted(dupes))}")
    if not members:
        issues.append("el plan necesita al menos un agente o un flujo")
    kbs = {k.name for k in plan.knowledge_bases}
    agents = {a.name for a in plan.agents}
    for a in plan.agents:
        missing = [k for k in a.knowledge if k not in kbs]
        if missing:
            issues.append(f"el agente {a.name} usa bases de conocimiento que no están en el plan: {', '.join(missing)}")
    for c in plan.channels:
        if c.agent not in agents:
            issues.append(f"el canal {c.provider} apunta a un agente inexistente: {c.agent}")
    for e in plan.evals:
        if e.member not in members:
            issues.append(f"la eval {e.name} es de un miembro inexistente: {e.member}")
    covered = {e.member for e in plan.evals}
    uncovered = [m for m in members if m not in covered]
    if uncovered:
        issues.append(f"cada agente y flujo necesita al menos una eval de aceptación: faltan {', '.join(uncovered)}")
    for w in plan.workflows:
        ids = [s.id for s in w.steps]
        if len(ids) != len(set(ids)):
            issues.append(f"el flujo {w.name} tiene pasos con el mismo id")
        if w.trigger.kind == "cron" and not w.trigger.schedule:
            issues.append(f"el flujo {w.name} es programado pero no tiene expresión cron")
    if plan.interface is not None:
        for screen in plan.interface.screens:
            for comp in screen.components:
                src = comp.source
                if src.startswith("kb:") and src[3:].split(".", 1)[0] not in kbs:
                    issues.append(f"el componente «{comp.title}» usa una base inexistente: {src}")
                if src.startswith("agent:") and src[6:] not in agents:
                    issues.append(f"el componente «{comp.title}» usa un agente inexistente: {src}")
                if src.startswith("workflow:") and src[9:] not in {w.name for w in plan.workflows}:
                    issues.append(f"el componente «{comp.title}» usa un flujo inexistente: {src}")
    return issues


def validate_plan(data: Any) -> tuple[Plan | None, list[str]]:
    """Parse a plan; on failure return the issues as short Spanish messages with their location."""
    try:
        return Plan.model_validate(data), []
    except ValidationError as exc:
        out: list[str] = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err.get("loc", ())) or "plan"
            out.append(f"{where}: {err.get('msg', 'no válido')}")
        return None, out


def plan_json_schema() -> dict[str, Any]:
    return Plan.model_json_schema()
