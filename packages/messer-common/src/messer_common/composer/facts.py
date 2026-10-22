"""What a request says (and leaves open), extracted without a model.

Used by the offline gate, the question bank (ask only about what is missing) and the offline planner. The
extraction is conservative: it only records what the text states explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import amounts_eur, bare_numbers, detect_language, fold, has_any

CHANNEL_TERMS: dict[str, tuple[str, ...]] = {
    "whatsapp": ("whatsapp", "whats app", "wasap"),
    "phone": (
        "telefono",
        "por telefono",
        "llamada*",
        "llamar",
        "phone",
        "phone calls",
        "calls",
        "call center",
        "centralita",
        "telefonica*",
    ),
    "slack": ("slack",),
    "teams": ("teams", "microsoft teams"),
    "telegram": ("telegram",),
    "email": (
        "por email",
        "por correo",
        "por correo electronico",
        "via email",
        "by email",
        "over email",
        "responder correos",
        "responder emails",
        "responda emails",
        "answer emails",
        "buzon",
        "inbox",
        "canal de email",
        "email channel",
    ),
    "web": ("web", "pagina web", "widget", "chat web", "web chat", "website", "sitio web"),
}

APPROVAL_TERMS = (
    "aprobacion*",
    "aprobar",
    "apruebe",
    "approval*",
    "approve*",
    "visto bueno",
    "autoriza*",
    "authoriz*",
    "validacion humana",
    "human approval",
    "revision humana",
    "human review",
    "sign off",
    "supervision",
)
DOCUMENT_TERMS = (
    "pdf*",
    "documento*",
    "document*",
    "condiciones",
    "terminos",
    "terms",
    "politica*",
    "policy",
    "policies",
    "manual*",
    "catalogo*",
    "catalog*",
    "faq",
    "preguntas frecuentes",
    "contrato*",
    "contract*",
    "normativa",
    "procedimiento*",
    "guia*",
    "guide*",
    "base de conocimiento",
    "knowledge base",
)
TABLE_TERMS = (
    "tabla",
    "tablas",
    "table",
    "tables",
    "hoja de calculo",
    "spreadsheet",
    "excel",
    "csv",
    "base de datos",
    "database",
    "erp",
    "crm",
)
DASHBOARD_TERMS = (
    "dashboard*",
    "panel",
    "paneles",
    "cuadro de mando",
    "cuadro de mandos",
    "informe*",
    "report*",
    "kpi*",
    "metricas",
    "metrics",
    "grafico*",
    "chart*",
    "app interna",
    "internal app",
    "pantalla*",
    "screen*",
)
CUSTOMER_TERMS = (
    "cliente*",
    "customer*",
    "usuario*",
    "user*",
    "paciente*",
    "patient*",
    "alumno*",
    "student*",
    "huesped*",
    "guest*",
    "ciudadano*",
    "socio*",
    "member*",
)
INTERNAL_TERMS = (
    "empleado*",
    "employee*",
    "equipo",
    "team",
    "interno",
    "internal",
    "plantilla",
    "staff",
    "comercial*",
    "sales team",
    "agentes de soporte",
)
SCHEDULE_TERMS = {
    "0 8 * * 1-5": ("cada dia laborable", "todos los dias laborables", "every weekday", "cada manana", "every morning"),
    "0 8 * * *": ("cada dia", "todos los dias", "diariamente", "diario", "every day", "daily"),
    "0 8 * * 1": ("cada lunes", "cada semana", "semanal*", "every monday", "every week", "weekly"),
    "0 8 1 * *": ("cada mes", "mensual*", "every month", "monthly", "a principio de mes", "start of the month"),
}
EMAIL_TRIGGER_TERMS = (
    "cuando llegue un email",
    "cuando llegue un correo",
    "when an email arrives",
    "emails entrantes",
    "correos entrantes",
    "incoming email*",
    "cada email que llegue",
    "every email",
)
WEBHOOK_TERMS = (
    "webhook",
    "desde mi erp",
    "desde el erp",
    "from my erp",
    "from the erp",
    "desde mi crm",
    "from my crm",
    "api externa",
    "external api",
)
FILE_TERMS = ("cuando se suba", "cuando suba", "when a file is uploaded", "nuevo archivo", "new file", "al subir")

# Subjects: (match terms, singular noun es, plural noun es, english plural, table columns)
SUBJECTS: list[tuple[tuple[str, ...], str, str, str, list[dict[str, str]]]] = [
    (
        ("factura*", "invoice*", "facturacion", "billing", "cobro*"),
        "factura",
        "facturas",
        "invoices",
        [
            {"name": "numero", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "importe", "type": "numeric"},
            {"name": "estado", "type": "text"},
            {"name": "fecha_emision", "type": "date"},
            {"name": "fecha_vencimiento", "type": "date"},
        ],
    ),
    (
        ("pedido*", "order*", "envio*", "shipment*", "entrega*", "delivery"),
        "pedido",
        "pedidos",
        "orders",
        [
            {"name": "numero", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "importe", "type": "numeric"},
            {"name": "estado", "type": "text"},
            {"name": "fecha", "type": "date"},
        ],
    ),
    (
        ("reserva*", "booking*", "reservation*", "cita*", "appointment*"),
        "reserva",
        "reservas",
        "bookings",
        [
            {"name": "codigo", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "fecha", "type": "timestamp"},
            {"name": "estado", "type": "text"},
        ],
    ),
    (
        ("ticket*", "incidencia*", "incident*", "averia*", "soporte tecnico", "support ticket*"),
        "incidencia",
        "incidencias",
        "tickets",
        [
            {"name": "codigo", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "prioridad", "type": "text"},
            {"name": "estado", "type": "text"},
            {"name": "fecha", "type": "timestamp"},
        ],
    ),
    (
        ("contrato*", "contract*"),
        "contrato",
        "contratos",
        "contracts",
        [
            {"name": "codigo", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "fecha_inicio", "type": "date"},
            {"name": "fecha_fin", "type": "date"},
            {"name": "estado", "type": "text"},
        ],
    ),
    (
        ("candidato*", "candidate*", "cv", "curriculum*", "seleccion de personal", "recruit*", "hiring"),
        "candidatura",
        "candidaturas",
        "applications",
        [
            {"name": "nombre", "type": "text"},
            {"name": "puesto", "type": "text"},
            {"name": "estado", "type": "text"},
            {"name": "fecha", "type": "date"},
        ],
    ),
    (
        ("producto*", "product*", "inventario", "inventory", "stock"),
        "producto",
        "productos",
        "products",
        [
            {"name": "referencia", "type": "text"},
            {"name": "nombre", "type": "text"},
            {"name": "precio", "type": "numeric"},
            {"name": "stock", "type": "integer"},
        ],
    ),
]

# Actions that typically need an approval: (match terms, workflow name, title es, title en)
APPROVAL_ACTIONS: list[tuple[tuple[str, ...], str, str, str]] = [
    (
        ("nota de credito", "notas de credito", "credit note*", "abono*", "rectificativa*"),
        "nota_credito",
        "Nota de crédito",
        "Credit note",
    ),
    (("reembolso*", "refund*", "devolucion*", "devolver"), "reembolso", "Reembolso", "Refund"),
    (("descuento*", "discount*"), "descuento", "Descuento", "Discount"),
    (("pago*", "payment*", "transferencia*", "transfer*"), "pago", "Pago", "Payment"),
    (("compra*", "purchase*", "pedido de compra", "purchase order*"), "compra", "Compra", "Purchase"),
    (("presupuesto*", "quote*", "oferta*", "offer*"), "presupuesto", "Presupuesto", "Quote"),
    (("gasto*", "expense*"), "gasto", "Gasto", "Expense"),
    (
        ("envio de email*", "enviar email*", "send email*", "enviar correo*"),
        "envio_email",
        "Envío de email",
        "Email sending",
    ),
]


@dataclass
class RequestFacts:
    language: str
    channels: list[str] = field(default_factory=list)
    voice: bool = False
    approval: bool = False
    threshold: float | None = None
    approval_action: tuple[str, str, str] | None = None  # (workflow name, title es, title en)
    documents: bool = False
    tables: bool = False
    dashboard: bool = False
    pending_items: bool = False
    monthly_queries: bool = False
    audience: str | None = None  # "customers" | "internal"
    subject: tuple[str, str, str, list[dict[str, str]]] | None = None  # (singular, plural, english, columns)
    schedule: str | None = None
    email_trigger: bool = False
    webhook_trigger: bool = False
    file_trigger: bool = False
    connectors: list[str] = field(default_factory=list)

    @property
    def subject_plural(self) -> str:
        return self.subject[1] if self.subject else ""


CONNECTOR_TERMS: dict[str, tuple[str, ...]] = {
    "google_drive": ("google drive", "drive"),
    "gmail": ("gmail",),
    "google_calendar": ("google calendar", "calendario de google"),
    "onedrive": ("onedrive",),
    "sharepoint": ("sharepoint",),
    "outlook": ("outlook",),
    "notion": ("notion",),
    "hubspot": ("hubspot",),
    "salesforce": ("salesforce",),
    "postgres": ("postgres", "postgresql"),
    "mysql": ("mysql",),
    "sqlserver": ("sql server", "sqlserver"),
}


def extract_facts(request: str, answers: dict[str, str] | None = None) -> RequestFacts:
    text = request
    extra = " ".join(v for v in (answers or {}).values() if v)
    full = f"{text} {extra}".strip()
    facts = RequestFacts(language=detect_language(text))

    for provider, terms in CHANNEL_TERMS.items():
        if provider == "email" and has_any(full, EMAIL_TRIGGER_TERMS):
            continue  # "when an email arrives" is a trigger, not a channel
        if has_any(full, terms):
            facts.channels.append(provider)
    if "web" in facts.channels and not has_any(
        full,
        (
            "chat web",
            "web chat",
            "widget",
            "en la web",
            "on the web",
            "en mi web",
            "on my website",
            "pagina web",
            "website",
        ),
    ):
        facts.channels.remove("web")  # "web" alone is too vague to be a channel
    facts.voice = "phone" in facts.channels or has_any(full, ("voz", "voice", "hablar", "speak"))

    facts.approval = has_any(full, APPROVAL_TERMS)
    amounts = amounts_eur(text) or amounts_eur(extra)
    if facts.approval:
        if amounts:
            facts.threshold = amounts[0]
        else:
            m = re.search(
                r"(?:mas de|superior(?:es)? a|por encima de|over|above|more than|mayor(?:es)? (?:de|que))"
                r"\s+(\d[\d.,]*)",
                fold(full),
            )
            if m:
                numbers = bare_numbers(m.group(1))
                facts.threshold = numbers[0] if numbers else None
        for terms, name, title_es, title_en in APPROVAL_ACTIONS:
            if has_any(full, terms):
                facts.approval_action = (name, title_es, title_en)
                break

    facts.documents = has_any(full, DOCUMENT_TERMS)
    facts.tables = has_any(full, TABLE_TERMS)
    facts.dashboard = has_any(full, DASHBOARD_TERMS)
    facts.pending_items = has_any(full, ("pendiente*", "pending", "sin pagar", "unpaid", "abiertas", "open"))
    facts.monthly_queries = has_any(
        full,
        (
            "consultas de este mes",
            "consultas del mes",
            "this month s queries",
            "queries this month",
            "consultas",
            "queries",
            "preguntas del mes",
        ),
    ) and has_any(full, ("mes", "month", "mensual*", "monthly"))
    if has_any(full, INTERNAL_TERMS) and not has_any(text, CUSTOMER_TERMS):
        facts.audience = "internal"
    elif has_any(full, CUSTOMER_TERMS):
        facts.audience = "customers"

    for terms, singular, plural, english, columns in SUBJECTS:
        if has_any(full, terms):
            facts.subject = (singular, plural, english, columns)
            break

    for cron, terms in SCHEDULE_TERMS.items():
        if has_any(full, terms):
            facts.schedule = cron
            break
    facts.email_trigger = has_any(full, EMAIL_TRIGGER_TERMS)
    facts.webhook_trigger = has_any(full, WEBHOOK_TERMS)
    facts.file_trigger = has_any(full, FILE_TERMS)
    for key, terms in CONNECTOR_TERMS.items():
        if has_any(full, terms):
            facts.connectors.append(key)
    return facts
