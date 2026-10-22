"""The Composer's gate: only requests about *building* something reach the architect.

Two paths with the same output:

* the model path (fast tier) classifies with the ``classify_request`` tool (``GATE_SYSTEM``, ``GATE_TOOL``);
* the offline path (:func:`classify_offline`) is a keyword/intent heuristic in Spanish and English.

A rejection is polite, explains what the Composer does and suggests how to phrase a building request. Nothing
else runs (and nothing else is charged) for a rejected request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .text import detect_language, has_any, words

Category = Literal["build", "question", "chitchat", "content", "unsafe", "unclear"]

BUILD_VERBS = (
    "quiero",
    "necesito",
    "queremos",
    "necesitamos",
    "me gustaria",
    "nos gustaria",
    "crea*",
    "construi*",
    "construy*",
    "monta*",
    "automatiza*",
    "automatic*",
    "haz",
    "hazme",
    "desarrolla*",
    "disena*",
    "configura*",
    "implementa*",
    "prepara*",
    "build*",
    "create*",
    "make",
    "set up",
    "setup",
    "automate*",
    "develop*",
    "design*",
    "i want",
    "i need",
    "we want",
    "we need",
    "would like",
    "help me build",
    "ayudame a crear",
    "ayudame a montar",
)
BUILD_OBJECTS = (
    "asistente*",
    "agente*",
    "agent*",
    "assistant*",
    "chatbot*",
    "bot",
    "bots",
    "flujo*",
    "workflow*",
    "proceso*",
    "process*",
    "automatizacion*",
    "automation*",
    "panel",
    "dashboard*",
    "cuadro de mando*",
    "app",
    "aplicacion*",
    "application*",
    "interfaz",
    "interface*",
    "formulario*",
    "form*",
    "integracion*",
    "integration*",
    "base de conocimiento",
    "knowledge base",
    "buscador",
    "search",
    "clasificador",
    "classifier",
    "triaje",
    "triage",
    "aprobacion*",
    "approval*",
    "notificacion*",
    "notification*",
    "informe*",
    "report*",
    "canal",
    "channel*",
    "whatsapp",
    "slack",
    "telegram",
    "teams",
    "atencion al cliente",
    "customer support",
    "soporte",
    "support",
)
TASK_VERBS = (
    "responda*",
    "responder",
    "conteste*",
    "contestar",
    "atienda*",
    "atender",
    "clasifique*",
    "clasificar",
    "procese*",
    "procesar",
    "gestione*",
    "gestionar",
    "extraiga*",
    "extraer",
    "resuma*",
    "resumir",
    "revise*",
    "revisar",
    "avise*",
    "avisar",
    "notifique*",
    "notificar",
    "envie*",
    "enviar",
    "genere*",
    "generar",
    "answer*",
    "respond*",
    "reply",
    "handle*",
    "classify*",
    "process*",
    "manage*",
    "extract*",
    "summari*",
    "review*",
    "notify*",
    "send*",
    "generate*",
    "route*",
    "enrutar",
    "detecte*",
    "detect*",
    "valide*",
    "validate*",
    "envia*",
    "enviame",
    "manda*",
    "avisa*",
    "recuerda*",
    "remind*",
    "alert*",
    "alerta*",
    "registra*",
    "record*",
    "track*",
    "sincroniza*",
    "sync*",
    "importa*",
    "exporta*",
    "export*",
    "calcula*",
    "clasifica*",
)
CONTENT_NOUNS = (
    "receta*",
    "recipe*",
    "poema*",
    "poem*",
    "cuento*",
    "story",
    "stories",
    "chiste*",
    "joke*",
    "ensayo*",
    "essay*",
    "cancion*",
    "song*",
    "redaccion",
    "articulo*",
    "article*",
    "carta de amor",
    "love letter",
)
STRONG_VERBS = ("automatiza*", "automate*", "construi*", "construy*", "build*", "crea*", "create*", "monta*", "set up")
SCHEDULE_HINTS = (
    "cada dia",
    "cada lunes",
    "cada martes",
    "cada miercoles",
    "cada jueves",
    "cada viernes",
    "cada semana",
    "cada mes",
    "todos los dias",
    "todas las semanas",
    "every day",
    "every week",
    "every month",
    "every monday",
    "daily",
    "weekly",
    "monthly",
    "cuando llegue",
    "cuando entre",
    "when a new",
    "when an",
    "cada vez que",
    "every time",
)
CONTENT_REQUESTS = (
    "escribe un poema",
    "escribeme un poema",
    "cuentame un chiste",
    "un chiste",
    "write a poem",
    "tell me a joke",
    "traduce",
    "translate",
    "resume este texto",
    "summarize this text",
    "redacta un email",
    "write an email",
    "escribe un articulo",
    "write an article",
    "haz mis deberes",
    "do my homework",
)
CHITCHAT = (
    "hola",
    "buenas",
    "buenos dias",
    "buenas tardes",
    "hello",
    "hi",
    "hey",
    "gracias",
    "thanks",
    "thank you",
    "que tal",
    "how are you",
    "quien eres",
    "who are you",
    "adios",
    "bye",
)
QUESTION_STARTS = (
    "que es",
    "que son",
    "quien es",
    "quien fue",
    "cual es",
    "cuales son",
    "cuando fue",
    "cuando es",
    "donde esta",
    "como se",
    "por que",
    "what is",
    "what are",
    "who is",
    "who was",
    "when was",
    "where is",
    "why is",
    "how does",
    "how do i",
    "cuanto es",
    "how much is",
    "cuantos",
)
UNSAFE = (
    "hackear",
    "hack into",
    "malware",
    "ransomware",
    "phishing",
    "robar contrasenas",
    "steal passwords",
    "suplantar",
    "impersonate",
    "spam masivo",
    "mass spam",
    "ddos",
    "keylogger",
    "fraude",
    "fraud scheme",
    "lavar dinero",
    "money laundering",
)


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    category: Category
    reason: str
    reply: str
    language: str

    def to_json(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "category": self.category,
            "reason": self.reason,
            "reply": self.reply,
            "language": self.language,
        }


REPLIES: dict[str, dict[str, str]] = {
    "es": {
        "question": (
            "Gracias por tu mensaje. El Composer construye soluciones (agentes, flujos, bases de conocimiento e "
            "interfaces) y no responde preguntas generales. Si quieres que un asistente responda este tipo de "
            "preguntas a tu equipo o a tus clientes, descríbelo así: «Quiero un asistente que responda preguntas "
            "sobre … usando …»."
        ),
        "chitchat": (
            "¡Hola! Soy el Composer de Messer. Cuéntame qué problema quieres resolver y lo construyo contigo, por "
            "ejemplo: «Quiero un asistente que responda a mis clientes por WhatsApp sobre sus pedidos»."
        ),
        "content": (
            "Gracias, pero el Composer no redacta textos sueltos: construye agentes, flujos e interfaces que trabajan "
            "por ti. Si quieres automatizar esa tarea, descríbela, por ejemplo: «Quiero un flujo que redacte un "
            "resumen de cada email que llegue y me lo envíe»."
        ),
        "unsafe": (
            "Lo siento, no puedo ayudarte con eso. El Composer construye soluciones de IA para tu negocio que "
            "cumplen las políticas de uso de Messer."
        ),
        "unclear": (
            "No estoy seguro de qué quieres construir. Describe el problema con un poco más de detalle: quién lo va "
            "a usar, qué debe hacer y con qué información, por ejemplo: «Quiero un asistente que clasifique los "
            "emails de soporte y avise al equipo de los urgentes»."
        ),
    },
    "en": {
        "question": (
            "Thanks for your message. The Composer builds solutions (agents, workflows, knowledge bases and "
            "interfaces) and does not answer general questions. If you want an assistant that answers this kind of "
            'question for your team or customers, describe it like this: "I want an assistant that answers '
            'questions about … using …".'
        ),
        "chitchat": (
            "Hi! I'm the Messer Composer. Tell me which problem you want to solve and I'll build it with you, for "
            'example: "I want an assistant that answers my customers on WhatsApp about their orders".'
        ),
        "content": (
            "Thanks, but the Composer doesn't write one-off texts: it builds agents, workflows and interfaces that "
            'work for you. If you want to automate that task, describe it, for example: "I want a workflow that '
            'summarizes every incoming email and sends me the summary".'
        ),
        "unsafe": (
            "Sorry, I can't help with that. The Composer builds AI solutions for your business that comply with "
            "Messer's acceptable use policy."
        ),
        "unclear": (
            "I'm not sure what you want to build. Describe the problem in a bit more detail: who will use it, what "
            'it should do and with which information, for example: "I want an assistant that triages support '
            'emails and alerts the team about urgent ones".'
        ),
    },
}


def rejection_reply(category: str, language: str) -> str:
    texts = REPLIES.get(language, REPLIES["es"])
    return texts.get(category, texts["unclear"])


def _decision(allowed: bool, category: Category, reason: str, language: str) -> GateDecision:
    return GateDecision(
        allowed=allowed,
        category=category,
        reason=reason,
        reply="" if allowed else rejection_reply(category, language),
        language=language,
    )


def classify_offline(text: str) -> GateDecision:
    """Deterministic gate: is this a request to build something?"""
    language = detect_language(text)
    tokens = words(text)
    if not tokens:
        return _decision(False, "unclear", "empty", language)
    if has_any(text, UNSAFE):
        return _decision(False, "unsafe", "unsafe_keywords", language)
    verbs = has_any(text, BUILD_VERBS)
    objects = has_any(text, BUILD_OBJECTS)
    tasks = has_any(text, TASK_VERBS)
    if (has_any(text, CONTENT_REQUESTS) or has_any(text, CONTENT_NOUNS)) and not objects:
        return _decision(False, "content", "one_off_content", language)
    if len(tokens) <= 4 and has_any(text, CHITCHAT) and not objects:
        return _decision(False, "chitchat", "greeting", language)
    folded = " ".join(tokens)
    if any(folded.startswith(q) for q in QUESTION_STARTS) and not (verbs and (objects or tasks)):
        return _decision(False, "question", "general_question", language)
    if objects and (verbs or tasks):
        return _decision(True, "build", "build_object_and_intent", language)
    if verbs and tasks:
        return _decision(True, "build", "build_intent_and_task", language)
    if tasks and has_any(text, SCHEDULE_HINTS):
        return _decision(True, "build", "automation_with_schedule_or_event", language)
    if has_any(text, STRONG_VERBS) and len(tokens) >= 3:
        return _decision(True, "build", "strong_build_verb", language)
    if objects and len(tokens) >= 6:
        return _decision(True, "build", "build_object_described", language)
    if len(tokens) < 4:
        return _decision(False, "unclear", "too_short", language)
    return _decision(False, "unclear", "no_build_intent", language)


# ------------------------------------------------------------------------------------------- model path

GATE_SYSTEM = """Eres la puerta de entrada del Composer de Messer, una plataforma que construye soluciones de IA para \
empresas: agentes (asistentes con herramientas y conocimiento), flujos de trabajo automáticos con disparadores y \
aprobaciones humanas, bases de conocimiento (documentos y tablas), conectores, interfaces (paneles, formularios, \
chats) y canales (WhatsApp, Slack, Teams, email, Telegram, teléfono).

Tu única tarea es clasificar el mensaje del usuario llamando a la herramienta `classify_request`:
- category "build": pide construir, automatizar o montar algo de lo anterior para su negocio o equipo, aunque lo \
describa con palabras de negocio ("quiero que mis clientes puedan…", "necesito que cada factura…").
- "question": una pregunta general o de conocimiento que no pide construir nada.
- "chitchat": saludos o conversación sin contenido.
- "content": pide redactar, traducir o resumir un texto concreto una sola vez.
- "unsafe": pide algo ilegal, dañino o contra las políticas de uso (malware, fraude, suplantación, spam).
- "unclear": demasiado vago para saber qué construir.

allowed es true solo para "build". En reply escribe, si allowed es false, una respuesta breve y amable en el \
idioma del usuario que explique qué hace el Composer y proponga cómo reformular la petición; si allowed es true, \
deja reply vacío. No respondas a la pregunta del usuario ni hagas nada más.

Ejemplos:
- "Quiero un asistente que responda a mis clientes sobre sus facturas usando nuestras condiciones" → build
- "Cada lunes envíame un resumen de las ventas de la semana" → build
- "¿Cuál es la capital de Francia?" → question
- "Hola" → chitchat
- "Tradúceme este párrafo al inglés" → content
- "Haz un bot que mande spam a mil números" → unsafe
"""

GATE_TOOL: dict[str, Any] = {
    "name": "classify_request",
    "description": "Clasifica el mensaje: ¿pide construir una solución en Messer?",
    "input_schema": {
        "type": "object",
        "properties": {
            "allowed": {"type": "boolean"},
            "category": {"type": "string", "enum": ["build", "question", "chitchat", "content", "unsafe", "unclear"]},
            "reason": {"type": "string", "description": "Motivo breve (interno)"},
            "reply": {"type": "string", "description": "Respuesta amable al usuario si allowed es false"},
        },
        "required": ["allowed", "category"],
    },
}


def parse_model_decision(data: Any, text: str) -> GateDecision | None:
    """Turn the ``classify_request`` input into a decision (``None`` when malformed)."""
    if not isinstance(data, dict):
        return None
    category = data.get("category")
    if category not in ("build", "question", "chitchat", "content", "unsafe", "unclear"):
        return None
    language = detect_language(text)
    allowed = category == "build"
    reply = str(data.get("reply") or "").strip()
    if not allowed and not reply:
        reply = rejection_reply(str(category), language)
    return GateDecision(
        allowed=allowed,
        category=category,  # type: ignore[arg-type]
        reason=str(data.get("reason") or "model")[:200],
        reply="" if allowed else reply[:1500],
        language=language,
    )
