"""The architect's product questions (2 to 4, never technical).

The offline path picks questions from a bank according to what the request leaves open (channels, approval
threshold, who approves, sources of knowledge) plus the questions every plan benefits from (the business name and
an example of a real question with its correct answer, which becomes an acceptance eval). The model path asks the
fast tier with the ``ask_questions`` tool and falls back to the bank when the answer is malformed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .facts import RequestFacts

MIN_QUESTIONS = 2
MAX_QUESTIONS = 4


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    text: str
    text_en: str
    placeholder: str = ""
    placeholder_en: str = ""

    def to_json(self, language: str = "es") -> dict[str, Any]:
        en = language == "en"
        return {
            "id": self.id,
            "text": self.text_en if en else self.text,
            "placeholder": (self.placeholder_en if en else self.placeholder) or None,
        }


BANK: dict[str, Question] = {
    "company": Question(
        "company",
        "¿Cómo se llama tu empresa o el servicio que verán tus clientes?",
        "What is the name of your company or the service your customers will see?",
        "Por ejemplo: Talleres Ruiz",
        "For example: Ruiz Motors",
    ),
    "channels": Question(
        "channels",
        "¿Por dónde quieres atender: chat en tu web, WhatsApp, teléfono, email, Slack o Teams?",
        "Where should it serve people: web chat, WhatsApp, phone, email, Slack or Teams?",
        "Por ejemplo: WhatsApp y chat en la web",
        "For example: WhatsApp and web chat",
    ),
    "threshold": Question(
        "threshold",
        "¿A partir de qué importe debe pedir aprobación a una persona antes de actuar?",
        "Above which amount should a person approve before it acts?",
        "Por ejemplo: 500 €",
        "For example: €500",
    ),
    "approver": Question(
        "approver",
        "¿Quién debe dar la aprobación: un responsable (administrador) o cualquier persona del equipo?",
        "Who should approve: a manager (administrator) or anyone on the team?",
        "Por ejemplo: la responsable de facturación",
        "For example: the billing manager",
    ),
    "documents": Question(
        "documents",
        "¿Qué información debe consultar para responder bien (documentos, catálogos, políticas, hojas de cálculo)?",
        "Which information should it rely on to answer well (documents, catalogs, policies, spreadsheets)?",
        "Por ejemplo: el catálogo en PDF y la lista de precios",
        "For example: the PDF catalog and the price list",
    ),
    "example": Question(
        "example",
        "Cuéntame una pregunta o caso típico y cómo debería resolverse. Lo usaré para comprobar que funciona.",
        "Give me a typical question or case and how it should be resolved. I'll use it to check that it works.",
        "Por ejemplo: «¿Cuándo vence mi factura?» → indicar la fecha de vencimiento",
        'For example: "When is my invoice due?" → give the due date',
    ),
    "tone": Question(
        "tone",
        "¿Qué tono debe usar: cercano y de tú, o formal y de usted?",
        "Which tone should it use: friendly and casual, or formal?",
        "Por ejemplo: cercano pero profesional",
        "For example: friendly but professional",
    ),
    "escalation": Question(
        "escalation",
        "Cuando no sepa resolver algo, ¿qué debe hacer: pasar el caso a una persona (indica a quién) o pedir más "
        "datos al cliente?",
        "When it can't solve something, what should it do: hand the case to a person (say who) or ask the customer "
        "for more details?",
        "Por ejemplo: avisar a soporte@miempresa.es",
        "For example: notify support@mycompany.com",
    ),
    "audience": Question(
        "audience",
        "¿Quién lo va a usar: tus clientes, tu equipo interno o ambos?",
        "Who will use it: your customers, your internal team or both?",
        "Por ejemplo: mis clientes",
        "For example: my customers",
    ),
}


def select_questions(facts: RequestFacts) -> list[Question]:
    """2–4 product questions about what the request leaves open, most important first."""
    picked: list[str] = []
    if not facts.channels and facts.audience != "internal" and not facts.schedule and not facts.email_trigger:
        picked.append("channels")
    if facts.approval and facts.threshold is None:
        picked.append("threshold")
    if not facts.documents and not facts.tables and not facts.connectors:
        picked.append("documents")
    if facts.audience is None:
        picked.append("audience")
    picked.append("company")
    if facts.approval:
        picked.append("approver")
    picked.append("example")
    optional = ["tone", "escalation"]
    while len(picked) < MIN_QUESTIONS and optional:
        picked.append(optional.pop(0))
    ordered = list(dict.fromkeys(picked))[:MAX_QUESTIONS]
    return [BANK[q] for q in ordered]


# ------------------------------------------------------------------------------------------- model path

QUESTIONS_TOOL: dict[str, Any] = {
    "name": "ask_questions",
    "description": "Las 2–4 preguntas de producto que necesitas para proponer un buen plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": MIN_QUESTIONS,
                "maxItems": MAX_QUESTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Identificador corto en minúsculas"},
                        "text": {"type": "string", "description": "La pregunta, en el idioma del usuario"},
                        "placeholder": {"type": "string", "description": "Ejemplo de respuesta"},
                    },
                    "required": ["id", "text"],
                },
            }
        },
        "required": ["questions"],
    },
}

_TECHNICAL = re.compile(
    r"\b(api|sql|json|yaml|webhook|endpoint|modelo de lenguaje|llm|embedding|vector|token|prompt|python|base de datos "
    r"relacional|schema|esquema|oauth|cron)\b",
    re.IGNORECASE,
)


def parse_model_questions(data: Any) -> list[dict[str, Any]] | None:
    """Validate the ``ask_questions`` input: 2–4 distinct, non-technical questions (``None`` when not usable)."""
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        return None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(data["questions"]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if len(text) < 8 or _TECHNICAL.search(text):
            continue
        qid = re.sub(r"[^a-z0-9_]", "_", str(item.get("id") or f"q{i + 1}").lower())[:40] or f"q{i + 1}"
        if qid in seen:
            qid = f"{qid}_{i + 1}"
        seen.add(qid)
        out.append({"id": qid, "text": text[:400], "placeholder": str(item.get("placeholder") or "")[:200] or None})
    if not MIN_QUESTIONS <= len(out) <= MAX_QUESTIONS:
        return None
    return out
