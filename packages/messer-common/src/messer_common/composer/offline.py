"""The architect's deterministic path: plans without a model.

* :func:`offline_plan` — the matching template's plan adapted to the answers (business name, tone, who approves,
  approval threshold, channels, whether a dashboard was asked for) or, when no template fits, a heuristic plan built
  from what the request states (agents, workflows with triggers and approvals, knowledge, interface only when asked
  for, channels, acceptance evals that pass with the offline demo model, risks).
* :func:`adjust_offline` — applies a free-text adjustment ("quita el panel", "el umbral es 1.000 €", "añade
  Slack"…) to a plan; anything it cannot map becomes an explicit instruction for the agents.

Every function returns a validated :class:`~messer_common.composer.plan.Plan`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .facts import (
    CHANNEL_TERMS,
    DASHBOARD_TERMS,
    RequestFacts,
    extract_facts,
)
from .plan import (
    ApprovalRule,
    Plan,
    PlanAgent,
    PlanChannel,
    PlanComponent,
    PlanConnector,
    PlanEval,
    PlanInterface,
    PlanKnowledgeBase,
    PlanScreen,
    PlanStep,
    PlanTable,
    PlanTrigger,
    PlanWorkflow,
    validate_plan,
)
from .text import amounts_eur, bare_numbers, detect_language, fold, format_eur, has_any, ident, sentence

ROLE_ADMIN_TERMS = (
    "admin*",
    "responsable*",
    "director*",
    "gerente*",
    "jefe*",
    "jefa*",
    "manager*",
    "owner",
    "propietari*",
    "supervisor*",
    "direccion",
    "contabilidad",
    "finanzas",
    "finance",
    "billing manager",
)
ROLE_TEAM_TERMS = ("cualquier*", "equipo", "team", "anyone", "todos", "everyone", "cualquiera del equipo")
CHANNEL_LABELS = {
    "whatsapp": ("WhatsApp", "WhatsApp"),
    "phone": ("teléfono", "phone"),
    "slack": ("Slack", "Slack"),
    "teams": ("Microsoft Teams", "Microsoft Teams"),
    "telegram": ("Telegram", "Telegram"),
    "email": ("email", "email"),
    "web": ("chat web", "web chat"),
}


class OfflinePlanError(ValueError):
    """The deterministic planner produced an invalid plan (a bug: the issues are listed)."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


# ============================================================================================== answers


@dataclass
class Answers:
    company: str | None = None
    channels: list[str] | None = None
    threshold: float | None = None
    approver_role: str | None = None
    documents: list[str] | None = None
    example_question: str | None = None
    example_answer: str | None = None
    tone: str | None = None  # "formal" | "friendly" | free text
    escalation: str | None = None
    escalation_email: str | None = None
    audience: str | None = None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _clean(value: str | None, limit: int = 300) -> str | None:
    text = re.sub(r"\s+", " ", (value or "")).strip().strip("«»\"'“”")
    if not text or fold(text) in {"no", "ninguno", "ninguna", "nada", "none", "n/a", "-", "no se", "no lo se"}:
        return None
    return text[:limit]


def interpret_answers(answers: dict[str, str] | None) -> Answers:
    raw = {k: v for k, v in (answers or {}).items() if isinstance(v, str)}
    out = Answers()
    company = _clean(raw.get("company"), 80)
    if company:
        company = re.sub(
            r"^(?:se llama|la empresa es|somos|es|nos llamamos|it is|we are|it's)\s+", "", company, flags=re.IGNORECASE
        ).rstrip(".")
        out.company = company or None
    if (channels := _clean(raw.get("channels"))) is not None:
        found = [p for p, terms in CHANNEL_TERMS.items() if has_any(channels, terms)]
        if has_any(channels, ("web", "chat", "pagina", "website")) and "web" not in found:
            found.append("web")
        if has_any(channels, ("email", "correo", "mail")) and "email" not in found:
            found.append("email")
        out.channels = found
    if (threshold := _clean(raw.get("threshold"))) is not None:
        numbers = amounts_eur(threshold) or bare_numbers(threshold)
        out.threshold = numbers[0] if numbers else None
    if (approver := _clean(raw.get("approver"))) is not None:
        if has_any(approver, ROLE_TEAM_TERMS) and not has_any(approver, ROLE_ADMIN_TERMS):
            out.approver_role = "builder"
        else:
            out.approver_role = "admin"
    if (docs := _clean(raw.get("documents"), 500)) is not None:
        parts = [p.strip(" .") for p in re.split(r",|;| y | and |\n", docs) if p.strip(" .")]
        out.documents = [p[:1].upper() + p[1:] for p in parts][:8]
    if (example := _clean(raw.get("example"), 600)) is not None:
        q, a = _split_example(example)
        out.example_question, out.example_answer = q, a
    if (tone := _clean(raw.get("tone"))) is not None:
        if has_any(tone, ("formal", "usted", "serio", "formally")):
            out.tone = "formal"
        elif has_any(tone, ("cercano*", "tu", "tutea*", "informal", "friendly", "casual", "amable", "close")):
            out.tone = "friendly"
        else:
            out.tone = tone
    if (escalation := _clean(raw.get("escalation"))) is not None:
        out.escalation = escalation
        match = _EMAIL.search(escalation)
        out.escalation_email = match.group(0) if match else None
    if (audience := _clean(raw.get("audience"))) is not None:
        both = has_any(audience, ("ambos", "los dos", "both", "todos"))
        internal = has_any(audience, ("equipo", "interno", "empleado*", "team", "internal", "staff"))
        out.audience = "both" if both else ("internal" if internal else "customers")
    return out


def _split_example(text: str) -> tuple[str, str | None]:
    """``"¿Cuándo vence? → la fecha de vencimiento"`` → (question, expected answer)."""
    for sep in ("→", "->", "=>", " debería ", " should ", " respuesta:", " answer:"):
        if sep in text:
            q, _, a = text.partition(sep)
            return q.strip(" «»\"'"), (a.strip(" «»\"'.:") or None)
    if "?" in text:
        q, _, a = text.partition("?")
        return f"{q.strip(' «»')}?".strip(), (a.strip(" «»\"'.:-") or None)
    return text.strip(" «»\"'"), None


# ============================================================================================== helpers


def _validated(data: dict[str, Any]) -> Plan:
    plan, issues = validate_plan(data)
    if plan is None:
        raise OfflinePlanError(issues)
    return plan


def _company_line(company: str, en: bool) -> str:
    return (
        f"You work for {company}; introduce yourself on its behalf."
        if en
        else (f"Trabajas para {company}; preséntate en su nombre.")
    )


def _tone_line(tone: str, en: bool) -> str:
    if tone == "formal":
        return "Use a formal, courteous tone." if en else "Usa un tono formal y trata al cliente de usted."
    if tone == "friendly":
        return (
            "Use a friendly, close and professional tone."
            if en
            else ("Usa un tono cercano y profesional, tuteando al cliente.")
        )
    return f"Tone: {tone}." if en else f"Tono: {sentence(tone)}"


def _escalation_line(answers: Answers, en: bool) -> str:
    target = answers.escalation_email or answers.escalation or ""
    if en:
        return f"When you cannot solve something, say so clearly and hand the case over: {sentence(target)}"
    return f"Cuando no puedas resolver algo, dilo con claridad y deriva el caso: {sentence(target)}"


def _greeting_with_company(greeting: str, company: str, en: bool) -> str:
    if company.lower() in greeting.lower():
        return greeting
    first, sep, rest = greeting.partition(".")
    if sep and ("soy " in first.lower() or "i'm " in first.lower() or "i am " in first.lower()):
        joiner = " at " if en else " de "
        return f"{first}{joiner}{company}.{rest}"
    return (
        f"{company}: {greeting}"
        if greeting
        else (
            f"Hello, this is {company}'s assistant. How can I help?"
            if en
            else f"Hola, soy el asistente de {company}. ¿En qué puedo ayudarte?"
        )
    )


def retarget_amount(text: str, old: float, new: float) -> str:
    """Replace an approval threshold written in prose (``"500 €"``, ``"€500"``, ``"500 euros"``)."""
    if not text or old == new:
        return text
    old_forms = {format_eur(old).replace(" €", ""), str(int(old)) if float(old).is_integer() else str(old)}
    new_text = format_eur(new).replace(" €", "")
    out = text
    for form in sorted(old_forms, key=len, reverse=True):
        esc = re.escape(form)
        out = re.sub(rf"(?<![\d.,]){esc}(\s*(?:€|euros?\b))", rf"{new_text}\1", out)
        out = re.sub(rf"(€\s*){esc}(?![\d.,])", rf"\g<1>{new_text}", out)
        out = re.sub(rf"(>\s*=?\s*){esc}(?![\d.,])", rf"\g<1>{new_text.replace('.', '')}", out)
    return out


def _apply_threshold(data: dict[str, Any], new: float) -> list[float]:
    """Set every approval rule with a threshold to ``new`` and rewrite the amounts in the texts."""
    olds: set[float] = set()
    for collection in ("agents", "workflows"):
        for member in data.get(collection, []):
            for rule in member.get("approvals", []):
                if rule.get("threshold") is not None and float(rule["threshold"]) != new:
                    olds.add(float(rule["threshold"]))
                    rule["threshold"] = new
    for old in olds:
        for rule_holder in (*data.get("agents", []), *data.get("workflows", [])):
            for rule in rule_holder.get("approvals", []):
                rule["condition"] = retarget_amount(str(rule.get("condition") or ""), old, new)
            for key in ("instructions", "description", "title", "greeting"):
                if isinstance(rule_holder.get(key), str):
                    rule_holder[key] = retarget_amount(rule_holder[key], old, new)
            for step in rule_holder.get("steps", []):
                for key in ("title", "description"):
                    if isinstance(step.get(key), str):
                        step[key] = retarget_amount(step[key], old, new)
        for key in ("goal", "summary"):
            data[key] = retarget_amount(str(data.get(key) or ""), old, new)
        data["risks"] = [retarget_amount(r, old, new) for r in data.get("risks", [])]
        for e in data.get("evals", []):
            e["input"] = {
                k: (_scaled(v, old, new) if k in ("importe", "amount") else v) for k, v in e.get("input", {}).items()
            }
            if isinstance(e["input"].get("prompt"), str):
                e["input"]["prompt"] = _scaled_prompt(e["input"]["prompt"], old, new)
        if data.get("interface"):
            data["interface"]["justification"] = retarget_amount(data["interface"].get("justification", ""), old, new)
    return sorted(olds)


def _scaled(value: Any, old: float, new: float) -> Any:
    """Keep eval amounts on the same side of a moved threshold (above stays above, below stays below)."""
    if not isinstance(value, int | float) or old <= 0:
        return value
    scaled = round(float(value) * new / old, 2)
    return int(scaled) if float(scaled).is_integer() else scaled


def _scaled_prompt(prompt: str, old: float, new: float) -> str:
    amounts = amounts_eur(prompt)
    out = prompt
    for amount in amounts:
        out = retarget_amount(out, amount, float(_scaled(amount, old, new)))
    return out


def _ensure_channels(data: dict[str, Any], requested: list[str], en: bool) -> None:
    agents = [a["name"] for a in data.get("agents", [])]
    if not agents:
        return
    present = {c["provider"] for c in data.get("channels", [])}
    for provider in requested:
        if provider in present:
            continue
        label = CHANNEL_LABELS.get(provider, (provider, provider))[1 if en else 0]
        data.setdefault("channels", []).append(
            {
                "provider": provider,
                "agent": agents[0],
                "purpose": f"Serve people on {label}" if en else f"Atender por {label}",
            }
        )
    voice_agents = {c["agent"] for c in data.get("channels", []) if c["provider"] == "phone"}
    for agent in data.get("agents", []):
        if agent["name"] in voice_agents:
            agent["voice"] = True


# ============================================================================================== template


def adapt_template_plan(base: Plan, request: str, answers: dict[str, str] | None) -> Plan:
    """The template's plan adjusted to this request and its answers."""
    facts = extract_facts(request, answers)
    ans = interpret_answers(answers)
    en = facts.language == "en"
    data = base.model_dump(mode="json")
    for agent in data["agents"]:
        extra: list[str] = []
        if ans.company:
            extra.append(_company_line(ans.company, en))
            agent["greeting"] = _greeting_with_company(agent.get("greeting") or "", ans.company, en)
        if ans.tone:
            extra.append(_tone_line(ans.tone, en))
        if ans.escalation:
            extra.append(_escalation_line(ans, en))
        if extra:
            agent["instructions"] = (agent["instructions"].rstrip() + "\n" + "\n".join(extra)).strip()
    threshold = ans.threshold if ans.threshold is not None else facts.threshold
    if threshold is not None and threshold > 0:
        _apply_threshold(data, threshold)
    if ans.approver_role:
        for member in (*data["agents"], *data["workflows"]):
            for rule in member.get("approvals", []):
                rule["approver_role"] = ans.approver_role
    requested: list[str] = list(dict.fromkeys([*facts.channels, *(ans.channels or [])]))
    _ensure_channels(data, requested, en)
    if data.get("interface") and not has_any(request, DASHBOARD_TERMS):
        data["interface"] = None
        data["risks"] = [
            *data.get("risks", []),
            (
                "No interface was proposed because the request does not ask for one; it can be added later."
                if en
                else "No se propone interfaz porque la petición no la pide; puedes añadirla después."
            ),
        ]
    if ans.example_question and data["agents"]:
        data["evals"].append(_example_eval(data["agents"][0]["name"], ans.example_question, data["evals"]))
    if ans.company:
        data["summary"] = f"{data['summary'].rstrip()} ({ans.company})"
    return _validated(data)


def _example_eval(member: str, question: str, existing: list[dict[str, Any]]) -> dict[str, Any]:
    names = {e["name"] for e in existing}
    name, n = "caso_del_cliente", 2
    while name in names:
        name, n = f"caso_del_cliente_{n}", n + 1
    return {"member": member, "name": name, "input": {"prompt": question[:500]}, "expect": "min_length", "value": "20"}


# ============================================================================================== heuristic


def _docs_described(request: str, ans: Answers, en: bool) -> list[str]:
    if ans.documents:
        return ans.documents
    found: list[str] = []
    catalog = [
        (("condiciones", "terminos", "terms"), "Condiciones generales (PDF)", "Terms and conditions (PDF)"),
        (("politica*", "policy", "policies"), "Políticas", "Policies"),
        (("catalogo*", "catalog*"), "Catálogo de productos", "Product catalog"),
        (("manual*",), "Manuales", "Manuals"),
        (("faq", "preguntas frecuentes"), "Preguntas frecuentes", "FAQ"),
        (("contrato*", "contract*"), "Contratos", "Contracts"),
        (("procedimiento*", "procedure*"), "Procedimientos internos", "Internal procedures"),
        (("normativa", "regulation*"), "Normativa", "Regulations"),
    ]
    for terms, es_label, en_label in catalog:
        if has_any(request, terms):
            found.append(en_label if en else es_label)
    if not found:
        found.append("Reference documents (PDF)" if en else "Documentos de referencia (PDF)")
    return found


QUERIES_TABLE = PlanTable(
    name="consultas",
    description="Consultas de clientes por canal",
    columns=[
        {"name": "fecha", "type": "timestamp"},
        {"name": "canal", "type": "text"},
        {"name": "tema", "type": "text"},
        {"name": "resuelta", "type": "boolean"},
    ],
)


def heuristic_plan(request: str, answers: dict[str, str] | None) -> Plan:
    """A plan built only from what the request and the answers state."""
    facts = extract_facts(request, answers)
    ans = interpret_answers(answers)
    en = facts.language == "en"
    subject = facts.subject
    plural = subject[2] if (subject and en) else (subject[1] if subject else "")
    singular = subject[0] if subject else ""
    audience = ans.audience or facts.audience or "customers"

    # ------------------------------------------------------------------ knowledge
    kbs: list[PlanKnowledgeBase] = []
    kb_name = ident(plural or ("knowledge" if en else "conocimiento"), fallback="conocimiento")
    tables: list[PlanTable] = []
    if facts.tables and subject:
        tables.append(PlanTable(name=ident(subject[1]), description=(f"{plural.capitalize()}"), columns=subject[3]))
    if facts.monthly_queries:
        tables.append(QUERIES_TABLE)
    has_docs = facts.documents or bool(ans.documents)
    if has_docs or tables:
        title = (
            (f"{plural.capitalize()} knowledge" if en else f"Conocimiento de {plural}")
            if plural
            else ("Knowledge base" if en else "Base de conocimiento")
        )
        kbs.append(
            PlanKnowledgeBase(
                name=kb_name,
                title=title,
                description=(
                    "Documents and data the assistant relies on"
                    if en
                    else "Documentos y datos en los que se apoya el asistente"
                ),
                documents=_docs_described(request, ans, en) if has_docs else [],
                tables=tables,
            )
        )

    # ------------------------------------------------------------------ workflows
    workflows: list[PlanWorkflow] = []
    approver_role = ans.approver_role or "admin"
    threshold = ans.threshold if ans.threshold is not None else facts.threshold
    approval_wf: PlanWorkflow | None = None
    if facts.approval:
        action = facts.approval_action or ("aprobacion", "Solicitud con aprobación", "Request with approval")
        wf_name, title_es, title_en = action
        title = title_en if en else title_es
        ref_field = "factura" if singular == "factura" else "referencia"
        fields = [ref_field, "importe", "motivo"]
        steps = [
            PlanStep(id="entrada", kind="input", title="Request" if en else "Solicitud", config={"fields": fields}),
        ]
        if threshold is not None:
            steps.append(
                PlanStep(
                    id="supera_umbral",
                    kind="condition",
                    title=(f"Over {format_eur(threshold)}?" if en else f"¿Más de {format_eur(threshold)}?"),
                    config={"expression": f"{{{{input.importe}}}} > {threshold:g}"},
                )
            )
        steps += [
            PlanStep(
                id="aprobacion",
                kind="approval",
                title="Human approval" if en else "Aprobación humana",
                description=(
                    f"A person with the {approver_role} role approves the {title.lower()}"
                    if en
                    else f"Una persona con rol {approver_role} aprueba la solicitud de {title.lower()}"
                ),
            ),
            PlanStep(
                id="registrar",
                kind="transform",
                title=f"Record the {title.lower()}" if en else f"Registrar {title.lower()}",
            ),
            PlanStep(id="resultado", kind="output", title="Result" if en else "Resultado"),
        ]
        rule = ApprovalRule(
            action="aprobacion",
            condition=(
                f"importe > {format_eur(threshold)}" if threshold is not None else ("always" if en else "siempre")
            ),
            threshold=threshold,
            field="importe" if threshold is not None else None,
            approver_role=approver_role,  # type: ignore[arg-type]
        )
        approval_wf = PlanWorkflow(
            name=wf_name,
            title=title,
            description=(
                f"Handles a {title.lower()} request"
                + (
                    f" and asks a person to approve it when it is over {format_eur(threshold)}"
                    if threshold
                    else " and asks a person to approve it"
                )
                if en
                else f"Gestiona una solicitud de {title.lower()}"
                + (
                    f" y pide aprobación humana cuando supera {format_eur(threshold)}"
                    if threshold
                    else " y pide aprobación humana"
                )
            ),
            trigger=PlanTrigger(
                kind="webhook" if facts.webhook_trigger else "manual",
                description="Requested by the assistant" if en else "Lo solicita el asistente",
            ),
            steps=steps,
            approvals=[rule],
        )
        workflows.append(approval_wf)
    if facts.schedule:
        steps = [PlanStep(id="entrada", kind="input", title="Start" if en else "Inicio")]
        if tables:
            table = tables[0]
            group = next((c["name"] for c in table.columns if c["name"] in ("estado", "canal", "tema")), None)
            sql = (
                f"SELECT {group}, count(*) AS total FROM {table.name} GROUP BY {group} ORDER BY total DESC"
                if group
                else f"SELECT count(*) AS total FROM {table.name}"
            )
            steps.append(
                PlanStep(
                    id="datos",
                    kind="sql_query",
                    title="Collect data" if en else "Recoger datos",
                    config={"kb": kb_name, "sql": sql},
                )
            )
        steps += [
            PlanStep(
                id="resumen",
                kind="llm",
                title="Write the summary" if en else "Redactar el resumen",
                description=sentence(request[:300]),
            ),
            PlanStep(id="resultado", kind="output", title="Report" if en else "Informe"),
        ]
        workflows.append(
            PlanWorkflow(
                name="informe_periodico",
                title="Periodic report" if en else "Informe periódico",
                description=("Prepares the periodic summary" if en else "Prepara el resumen periódico"),
                trigger=PlanTrigger(
                    kind="cron",
                    schedule=facts.schedule,
                    timezone="Europe/Madrid",
                    description="Scheduled" if en else "Programado",
                ),
                steps=steps,
            )
        )
    if facts.email_trigger:
        workflows.append(
            PlanWorkflow(
                name="procesar_email",
                title="Process incoming email" if en else "Procesar emails entrantes",
                description=(
                    "Classifies every incoming email and summarizes it"
                    if en
                    else "Clasifica cada email que llega y lo resume"
                ),
                trigger=PlanTrigger(kind="email", description="Inbound address" if en else "Dirección de entrada"),
                steps=[
                    PlanStep(id="entrada", kind="input", title="Email"),
                    PlanStep(
                        id="clasificar",
                        kind="llm",
                        title="Classify" if en else "Clasificar",
                        description=sentence(request[:300]),
                    ),
                    PlanStep(id="resultado", kind="output", title="Result" if en else "Resultado"),
                ],
            )
        )
    if facts.file_trigger and kbs:
        workflows.append(
            PlanWorkflow(
                name="procesar_documento",
                title="Process new documents" if en else "Procesar documentos nuevos",
                description=(
                    "Runs every time a file is uploaded" if en else "Se ejecuta cada vez que se sube un archivo"
                ),
                trigger=PlanTrigger(kind="file", description=kbs[0].title),
                steps=[
                    PlanStep(id="entrada", kind="input", title="File" if en else "Archivo"),
                    PlanStep(id="resumir", kind="llm", title="Summarize" if en else "Resumir"),
                    PlanStep(id="resultado", kind="output", title="Result" if en else "Resultado"),
                ],
            )
        )

    # ------------------------------------------------------------------ agent
    agents: list[PlanAgent] = []
    needs_agent = audience in ("customers", "both") or facts.channels or has_docs or not workflows
    if needs_agent:
        agent_name = ident(f"asistente_{subject[1]}" if subject else "asistente", fallback="asistente")
        title = (
            (f"{plural.capitalize()} assistant" if en else f"Asistente de {plural}")
            if plural
            else ("Assistant" if en else "Asistente")
        )
        lines: list[str] = []
        who = "customers" if en else "clientes"
        if audience == "internal":
            who = "the team" if en else "el equipo"
        if en:
            lines.append(f"You help {who}" + (f" with their {plural}." if plural else "."))
        else:
            lines.append(
                f"Ayudas a {'los ' if who == 'clientes' else ''}{who}" + (f" con sus {plural}." if plural else ".")
            )
        if has_docs:
            lines.append(
                "Answer from the knowledge base and cite the document you used; never invent data."
                if en
                else "Responde con la base de conocimiento y cita el documento que usas; nunca inventes datos."
            )
        if tables:
            lines.append(
                "Look records up in the tables before giving any figure."
                if en
                else "Consulta los registros en las tablas antes de dar cualquier dato."
            )
        if approval_wf is not None:
            limit = (
                f" over {format_eur(threshold)}"
                if (threshold and en)
                else (f" de más de {format_eur(threshold)}" if threshold else "")
            )
            lines.append(
                f"To process a {approval_wf.title.lower()} use the {approval_wf.name} workflow: it waits for a "
                f"person's approval{limit}."
                if en
                else f"Para tramitar una solicitud de {approval_wf.title.lower()} usa el flujo {approval_wf.name}: "
                f"las solicitudes{limit} esperan la aprobación de una persona."
            )
        if ans.company:
            lines.append(_company_line(ans.company, en))
        if ans.tone:
            lines.append(_tone_line(ans.tone, en))
        if ans.escalation:
            lines.append(_escalation_line(ans, en))
        lines.append("Reply in the user's language." if en else "Responde en el idioma del usuario.")
        tools: list[str] = ["current_datetime"]
        if has_docs:
            tools.insert(0, "knowledge_search")
        if tables:
            tools.append("sql_query")
        if amounts_eur(request):
            tools.append("calculator")
        if ans.escalation_email:
            tools.append("send_email")
        greeting = (
            f"Hello, I'm the {title.lower()}{(' at ' + ans.company) if ans.company else ''}. How can I help?"
            if en
            else f"Hola, soy el {title[0].lower() + title[1:]}{(' de ' + ans.company) if ans.company else ''}. "
            "¿En qué puedo ayudarte?"
        )
        agents.append(
            PlanAgent(
                name=agent_name,
                title=title,
                description=sentence(request[:400]),
                instructions="\n".join(lines),
                tools=list(dict.fromkeys(tools)),  # type: ignore[arg-type]
                knowledge=[kb.name for kb in kbs],
                approvals=[
                    ApprovalRule(
                        action=approval_wf.name,
                        condition=approval_wf.approvals[0].condition,
                        threshold=threshold,
                        field="importe" if threshold is not None else None,
                        approver_role=approver_role,  # type: ignore[arg-type]
                    )
                ]
                if approval_wf is not None
                else [],
                voice=facts.voice,
                greeting=greeting,
                model_tier="standard",
            )
        )

    # ------------------------------------------------------------------ channels
    channels: list[PlanChannel] = []
    requested: list[str] = list(dict.fromkeys([*facts.channels, *(ans.channels or [])]))
    if agents:
        for provider in requested:
            label = CHANNEL_LABELS.get(provider, (provider, provider))[1 if en else 0]
            channels.append(
                PlanChannel(
                    provider=provider,  # type: ignore[arg-type]
                    agent=agents[0].name,
                    purpose=f"Serve people on {label}" if en else f"Atender por {label}",
                )
            )
        if any(c.provider == "phone" for c in channels):
            agents[0].voice = True

    # ------------------------------------------------------------------ interface (only when asked for)
    interface: PlanInterface | None = None
    if facts.dashboard:
        components: list[PlanComponent] = []
        main = tables[0] if tables and tables[0].name != "consultas" else None
        if main is not None:
            pending = facts.pending_items and any(c["name"] == "estado" for c in main.columns)
            components.append(
                PlanComponent(
                    type="kpi",
                    title=(f"Pending {plural}" if en else f"{plural.capitalize()} pendientes")
                    if pending
                    else (f"Total {plural}" if en else f"Total de {plural}"),
                    source=f"kb:{kb_name}.{main.name}",
                )
            )
            components.append(
                PlanComponent(
                    type="data_table",
                    title=(f"Pending {plural}" if en else f"{plural.capitalize()} pendientes")
                    if pending
                    else (plural.capitalize()),
                    source=f"kb:{kb_name}.{main.name}",
                )
            )
            components.append(
                PlanComponent(
                    type="chart",
                    title=(f"{plural.capitalize()} by status" if en else f"{plural.capitalize()} por estado"),
                    source=f"kb:{kb_name}.{main.name}",
                )
            )
        if facts.monthly_queries and kbs:
            components.append(
                PlanComponent(
                    type="kpi",
                    title="Queries this month" if en else "Consultas este mes",
                    source=f"kb:{kb_name}.consultas",
                )
            )
            components.append(
                PlanComponent(
                    type="chart",
                    title="Queries by channel" if en else "Consultas por canal",
                    source=f"kb:{kb_name}.consultas",
                )
            )
        if approval_wf is not None:
            components.append(
                PlanComponent(
                    type="approvals_inbox",
                    title="Pending approvals" if en else "Pendientes de aprobación",
                    source="approvals",
                )
            )
        if agents and not components:
            components.append(PlanComponent(type="chat", title=agents[0].title, source=f"agent:{agents[0].name}"))
        if components:
            asked = next(
                (w for w in ("dashboard", "panel", "cuadro de mando", "informe", "report") if has_any(request, (w,))),
                "panel",
            )
            interface = PlanInterface(
                kind="app",
                title=(f"{plural.capitalize()} dashboard" if en else f"Panel de {plural}")
                if plural
                else ("Dashboard" if en else "Panel"),
                justification=(
                    f"The request explicitly asks for a {asked}."
                    if en
                    else f"La petición pide expresamente un {asked}."
                ),
                screens=[PlanScreen(title="Summary" if en else "Resumen", components=components)],
            )

    # ------------------------------------------------------------------ connectors
    connectors = [
        PlanConnector(
            key=key, purpose=("Mentioned in the request" if en else "Mencionado en la petición"), required=True
        )
        for key in facts.connectors
    ]

    # ------------------------------------------------------------------ evals (deterministic with the demo model)
    evals: list[PlanEval] = []
    for agent in agents:
        evals.append(
            PlanEval(
                member=agent.name,
                name="responde_con_contenido",
                input={"prompt": "Hello, can you help me?" if en else "Hola, ¿me puedes ayudar?"},
                expect="min_length",
                value="20",
            )
        )
        if "knowledge_search" in agent.tools:
            evals.append(
                PlanEval(
                    member=agent.name,
                    name="consulta_la_base_de_conocimiento",
                    input={
                        "prompt": "What do the terms say about deadlines?"
                        if en
                        else "¿Qué dicen las condiciones sobre los plazos?"
                    },
                    expect="tool_called",
                    value="knowledge_search",
                )
            )
        if approval_wf is not None and threshold is not None:
            big = max(threshold * 2, threshold + 100)
            noun = approval_wf.title.lower()
            evals.append(
                PlanEval(
                    member=agent.name,
                    name="solicitud_grande_pide_aprobacion",
                    input={
                        "prompt": (
                            f"I need a {noun} of {format_eur(big)} for F-1001"
                            if en
                            else f"Necesito una solicitud de {noun} de {format_eur(big)} para la F-1001"
                        )
                    },
                    expect="approval_required",
                    value=approval_wf.name,
                )
            )
    if approval_wf is not None:
        ref_field = approval_wf.steps[0].config.get("fields", ["referencia"])[0]
        if threshold is not None:
            evals.append(
                PlanEval(
                    member=approval_wf.name,
                    name="importe_pequeno_sin_aprobacion",
                    input={ref_field: "F-1001", "importe": max(round(threshold / 5, 2), 1), "motivo": "Prueba"},
                    expect="contains",
                    value="estado=completado",
                )
            )
            evals.append(
                PlanEval(
                    member=approval_wf.name,
                    name="importe_grande_pide_aprobacion",
                    input={ref_field: "F-1002", "importe": max(threshold * 2, threshold + 100), "motivo": "Prueba"},
                    expect="approval_required",
                    value="aprobacion",
                )
            )
        else:
            evals.append(
                PlanEval(
                    member=approval_wf.name,
                    name="pide_aprobacion",
                    input={ref_field: "F-1001", "importe": 100, "motivo": "Prueba"},
                    expect="approval_required",
                    value="aprobacion",
                )
            )
    for wf in workflows:
        if wf is approval_wf:
            continue
        evals.append(PlanEval(member=wf.name, name=f"{wf.name}_termina", input={}, expect="min_length", value="1"))
    if ans.example_question and agents:
        evals.append(
            PlanEval(
                member=agents[0].name,
                name="caso_del_cliente",
                input={"prompt": ans.example_question[:500]},
                expect="min_length",
                value="20",
            )
        )

    # ------------------------------------------------------------------ risks
    risks: list[str] = []
    if has_docs:
        risks.append(
            "Answers are only as good as the documents you upload: keep them up to date."
            if en
            else "Las respuestas dependen de los documentos que subas: mantenlos actualizados."
        )
    if tables:
        risks.append(
            "The tables start empty: load your data or connect your system before going live."
            if en
            else "Las tablas empiezan vacías: carga tus datos o conecta tu sistema antes de usarlo con clientes."
        )
    if any(c.provider not in ("web",) for c in channels):
        risks.append(
            "Channels run in demo mode until you add their credentials."
            if en
            else "Los canales funcionan en modo demo hasta que añadas sus credenciales."
        )
    if approval_wf is not None:
        risks.append(
            "Approvals expire after three days and are denied by default if nobody decides."
            if en
            else "Las aprobaciones caducan a los tres días y se deniegan por defecto si nadie decide."
        )
    if not risks:
        risks.append(
            "Review the generated instructions before publishing."
            if en
            else "Revisa las instrucciones generadas antes de publicar."
        )

    goal = sentence(request[:400])
    summary_parts = []
    if agents:
        summary_parts.append(f"1 agent ({agents[0].title})" if en else f"1 agente ({agents[0].title})")
    if workflows:
        summary_parts.append(f"{len(workflows)} workflow(s)" if en else f"{len(workflows)} flujo(s)")
    if kbs:
        summary_parts.append("a knowledge base" if en else "una base de conocimiento")
    if interface:
        summary_parts.append("a dashboard" if en else "un panel")
    if channels:
        labels = ", ".join(CHANNEL_LABELS.get(c.provider, (c.provider, c.provider))[1 if en else 0] for c in channels)
        summary_parts.append(("channels: " if en else "canales: ") + labels)
    summary = "Plan: " + "; ".join(summary_parts) + "."

    data = Plan.model_construct(
        goal=goal,
        summary=summary,
        template_id=None,
        agents=agents,
        workflows=workflows,
        knowledge_bases=kbs,
        connectors=connectors,
        interface=interface,
        channels=channels,
        evals=evals,
        risks=risks,
    ).model_dump(mode="json")
    return _validated(data)


# ============================================================================================== entry point


def offline_plan(request: str, answers: dict[str, str] | None, base: Plan | None) -> Plan:
    """Template plan adapted to the answers when a template fits, otherwise a heuristic plan."""
    if base is not None:
        return adapt_template_plan(base, request, answers)
    return heuristic_plan(request, answers)


# ============================================================================================== adjust


def _adjust_text(text: str) -> str:
    return " " + fold(text) + " "


def adjust_offline(plan: Plan, text: str) -> tuple[Plan, list[str]]:
    """Apply a free-text adjustment. Returns the new plan and the list of changes (in the adjustment's language)."""
    en = detect_language(text) == "en"
    data = plan.model_dump(mode="json")
    changes: list[str] = []
    folded = _adjust_text(text)
    remove_words = (
        "quita",
        "quitar",
        "elimina",
        "eliminar",
        "sin ",
        "no quiero",
        "remove",
        "without",
        "drop",
        "no necesito",
        "don't want",
        "do not want",
        "borra",
    )
    add_words = (
        "anade",
        "anadir",
        "agrega",
        "agregar",
        "incluye",
        "incluir",
        "tambien",
        "add",
        "include",
        "also",
        "con ",
        "quiero",
    )
    removing = any(w in folded for w in remove_words)
    adding = any(w in folded for w in add_words)

    # Approval threshold.
    amounts = amounts_eur(text)
    if amounts and (
        has_any(
            text,
            (
                "umbral",
                "threshold",
                "importe",
                "aprobacion*",
                "approval*",
                "a partir de",
                "mas de",
                "over",
                "above",
                "limite",
                "limit",
            ),
        )
        or len(amounts) == 1
    ):
        has_rules = any(
            r.get("threshold") is not None
            for m in (*data["agents"], *data["workflows"])
            for r in m.get("approvals", [])
        )
        if has_rules:
            olds = _apply_threshold(data, amounts[0])
            if olds:
                changes.append(
                    f"Approval threshold: {format_eur(amounts[0])}"
                    if en
                    else f"Umbral de aprobación: {format_eur(amounts[0])}"
                )

    # Who approves.
    if has_any(text, ("aprueb*", "aprobar", "approve*", "approver")):
        role = None
        if has_any(text, ROLE_TEAM_TERMS):
            role = "builder"
        elif has_any(text, ROLE_ADMIN_TERMS):
            role = "admin"
        if role:
            for member in (*data["agents"], *data["workflows"]):
                for rule in member.get("approvals", []):
                    rule["approver_role"] = role
            changes.append(f"Approver role: {role}" if en else f"Aprueba: rol {role}")

    # Channels.
    for provider, terms in CHANNEL_TERMS.items():
        if not has_any(text, terms) and not (provider == "email" and has_any(text, ("email", "correo"))):
            continue
        label = CHANNEL_LABELS.get(provider, (provider, provider))[1 if en else 0]
        present = any(c["provider"] == provider for c in data["channels"])
        if removing and present:
            data["channels"] = [c for c in data["channels"] if c["provider"] != provider]
            if provider == "phone":
                for agent in data["agents"]:
                    agent["voice"] = False
            changes.append(f"Channel removed: {label}" if en else f"Canal eliminado: {label}")
        elif adding and not present and data["agents"]:
            _ensure_channels(data, [provider], en)
            changes.append(f"Channel added: {label}" if en else f"Canal añadido: {label}")

    # Interface.
    if has_any(text, DASHBOARD_TERMS) or has_any(text, ("interfaz", "interface")):
        if removing and data.get("interface"):
            data["interface"] = None
            changes.append("Interface removed" if en else "Interfaz eliminada")
        elif adding and not data.get("interface"):
            components: list[dict[str, Any]] = []
            for kb in data["knowledge_bases"]:
                for table in kb.get("tables", []):
                    components.append(
                        {
                            "type": "data_table",
                            "title": table["name"].replace("_", " ").capitalize(),
                            "source": f"kb:{kb['name']}.{table['name']}",
                            "description": "",
                        }
                    )
            if any(m.get("approvals") for m in (*data["agents"], *data["workflows"])):
                components.append(
                    {
                        "type": "approvals_inbox",
                        "title": "Pendientes de aprobación" if not en else "Pending approvals",
                        "source": "approvals",
                        "description": "",
                    }
                )
            if not components and data["agents"]:
                agent = data["agents"][0]
                components.append(
                    {"type": "chat", "title": agent["title"], "source": f"agent:{agent['name']}", "description": ""}
                )
            if components:
                data["interface"] = {
                    "kind": "app",
                    "title": "Dashboard" if en else "Panel",
                    "justification": "Requested in the adjustment" if en else "Pedido al ajustar el plan",
                    "screens": [{"title": "Summary" if en else "Resumen", "components": components}],
                }
                changes.append("Dashboard added" if en else "Panel añadido")

    # Voice.
    if has_any(text, ("voz", "voice")) and data["agents"]:
        enable = not removing
        for agent in data["agents"]:
            agent["voice"] = enable
        changes.append(
            ("Voice enabled" if enable else "Voice disabled")
            if en
            else ("Voz activada" if enable else "Voz desactivada")
        )

    # Business name.
    company = re.search(
        r"(?:empresa|negocio|compania|company|business)\s+(?:se llama|es|is|called|:)\s+"
        r"([^\n.,;]{2,60})",
        text,
        flags=re.IGNORECASE,
    )
    if company and data["agents"]:
        name = company.group(1).strip(" «»\"'")
        for agent in data["agents"]:
            agent["instructions"] = agent["instructions"].rstrip() + "\n" + _company_line(name, en)
            agent["greeting"] = _greeting_with_company(agent.get("greeting") or "", name, en)
        changes.append(f"Business name: {name}" if en else f"Nombre del negocio: {name}")

    # Tone.
    if has_any(text, ("formal", "usted")) and data["agents"]:
        for agent in data["agents"]:
            agent["instructions"] = agent["instructions"].rstrip() + "\n" + _tone_line("formal", en)
        changes.append("Formal tone" if en else "Tono formal")
    elif has_any(text, ("cercano*", "tutea*", "informal", "friendly", "casual")) and data["agents"]:
        for agent in data["agents"]:
            agent["instructions"] = agent["instructions"].rstrip() + "\n" + _tone_line("friendly", en)
        changes.append("Friendly tone" if en else "Tono cercano")

    # Anything else becomes an explicit instruction for the agents.
    if not changes and data["agents"]:
        note = sentence(text[:500])
        for agent in data["agents"]:
            agent["instructions"] = (
                agent["instructions"].rstrip()
                + "\n"
                + ("Additional instruction: " if en else "Indicación adicional: ")
                + note
            )
        changes.append(("Added to the agents' instructions: " if en else "Añadido a las instrucciones: ") + note)
    elif not changes and data["workflows"]:
        for wf in data["workflows"]:
            wf["description"] = (wf["description"].rstrip() + " " + sentence(text[:300])).strip()
        changes.append(("Noted in the workflows: " if en else "Anotado en los flujos: ") + sentence(text[:300]))

    return _validated(data), changes


def channel_label(provider: str, language: str = "es") -> str:
    return CHANNEL_LABELS.get(provider, (provider, provider))[1 if language == "en" else 0]


def facts_summary(facts: RequestFacts) -> dict[str, Any]:
    """Facts as JSON (stored with the session for transparency)."""
    return {
        "language": facts.language,
        "channels": facts.channels,
        "voice": facts.voice,
        "approval": facts.approval,
        "threshold": facts.threshold,
        "documents": facts.documents,
        "tables": facts.tables,
        "dashboard": facts.dashboard,
        "audience": facts.audience,
        "subject": facts.subject[1] if facts.subject else None,
        "schedule": facts.schedule,
        "connectors": facts.connectors,
    }
