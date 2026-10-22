"""Small text helpers shared by the Composer's offline paths (gate, questions, planner, adjustments).

Everything here is deterministic and language-aware for Spanish and English: accent-insensitive matching,
language detection, amounts in euros and identifiers usable in plans (``^[a-z][a-z0-9_]{0,62}$``).
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")
_AMOUNT = re.compile(
    r"(?:(?:€|eur)\s*(?P<pre>\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?))"
    r"|(?:(?P<post>\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:€|eur\b|euros?\b|k€))",
    re.IGNORECASE,
)

_ES_HINTS = {
    "que",
    "quiero",
    "necesito",
    "para",
    "con",
    "los",
    "las",
    "una",
    "por",
    "del",
    "sobre",
    "cuando",
    "como",
    "nuestro",
    "nuestros",
    "nuestra",
    "clientes",
    "facturas",
    "tambien",
    "panel",
    "flujo",
    "aprobacion",
    "pedidos",
    "este",
    "mes",
    "hola",
    "gracias",
    "ayuda",
    "asistente",
    "correo",
    "telefono",
    "preguntas",
    "responda",
}
_EN_HINTS = {
    "the",
    "want",
    "need",
    "that",
    "with",
    "our",
    "their",
    "about",
    "when",
    "how",
    "customers",
    "invoices",
    "also",
    "dashboard",
    "workflow",
    "approval",
    "orders",
    "this",
    "month",
    "hello",
    "thanks",
    "help",
    "assistant",
    "email",
    "phone",
    "questions",
    "answers",
    "build",
    "create",
}


def fold(text: str) -> str:
    """Lowercase without accents (``"Crédito"`` → ``"credito"``)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def padded(text: str) -> str:
    """Folded text with single spaces and padding, so ``f" {term} " in padded(text)`` matches whole words."""
    return " " + " ".join(words(text)) + " "


def has_any(text: str, terms: tuple[str, ...] | list[str] | set[str]) -> bool:
    """Whole-word (or whole-phrase) match of any term, accent-insensitive; a trailing ``*`` matches a prefix."""
    hay = padded(text)
    for term in terms:
        t = " ".join(words(term.rstrip("*")))
        if not t:
            continue
        if term.endswith("*"):
            if f" {t}" in hay:
                return True
        elif f" {t} " in hay:
            return True
    return False


def detect_language(text: str) -> str:
    """``"es"`` or ``"en"`` (Spanish wins ties: the product is Spanish-first)."""
    tokens = set(words(text))
    if re.search(r"[áéíóúñ¿¡]", text.lower()):
        return "es"
    return "en" if len(tokens & _EN_HINTS) > len(tokens & _ES_HINTS) else "es"


def parse_number(raw: str) -> float | None:
    """``"1.250,50"`` → 1250.5, ``"500"`` → 500, ``"1,5"`` → 1.5, ``"2.000"`` → 2000."""
    value = raw.replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    elif value.count(".") == 1 and len(value.split(".")[1]) == 3:
        value = value.replace(".", "")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    try:
        return float(value)
    except ValueError:
        return None


def amounts_eur(text: str) -> list[float]:
    """Amounts written with a euro sign or the word euro(s), in order of appearance."""
    out: list[float] = []
    for match in _AMOUNT.finditer(text):
        raw = match.group("pre") or match.group("post") or ""
        number = parse_number(raw)
        if number is None:
            continue
        if match.group(0).lower().endswith("k€"):
            number *= 1000
        out.append(number)
    return out


def bare_numbers(text: str) -> list[float]:
    out: list[float] = []
    for raw in re.findall(r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?", text):
        number = parse_number(raw)
        if number is not None:
            out.append(number)
    return out


def ident(text: str, *, fallback: str = "elemento", max_len: int = 40) -> str:
    """A plan identifier from free text: ``"Nota de crédito"`` → ``"nota_de_credito"``."""
    base = "_".join(words(text))[:max_len].strip("_")
    if not base or not base[0].isalpha():
        base = f"{fallback}_{base}".strip("_") if base else fallback
    return re.sub(r"_+", "_", base)[:63]


def sentence(text: str) -> str:
    """Trimmed text ending with punctuation."""
    value = re.sub(r"\s+", " ", text).strip()
    if value and value[-1] not in ".!?…":
        value += "."
    return value


def format_eur(value: float) -> str:
    """``500.0`` → ``"500 €"``, ``1250.5`` → ``"1.250,50 €"`` (Spanish formatting)."""
    if float(value).is_integer():
        whole = f"{int(value):,}".replace(",", ".")
        return f"{whole} €"
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} €"
