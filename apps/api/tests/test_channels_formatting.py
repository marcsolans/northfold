"""Provider formatting of agent answers and splitting of long replies."""

from __future__ import annotations

import pytest

from messer_common.channels import get_adapter
from messer_common.channels.base import InboundRequest, InvalidConfig
from messer_common.channels.email import is_auto_message, normalize
from messer_common.channels.formatting import single_line, split_text, text_of, to_html, to_plain, to_slack, to_whatsapp
from messer_common.channels.texts import notice

MD = "# Factura 12\n\nHola **Ana**, vence el *30*.\n\n- Importe: 120 €\n- [Ver](https://x.example/f/12)\n\n`ref` & <ok>"


def test_whatsapp_and_slack_formatting() -> None:
    assert to_whatsapp(MD) == (
        "*Factura 12*\n\nHola *Ana*, vence el _30_.\n\n• Importe: 120 €\n• Ver (https://x.example/f/12)\n\n`ref` & <ok>"
    )
    assert to_slack(MD) == (
        "*Factura 12*\n\nHola *Ana*, vence el _30_.\n\n• Importe: 120 €\n• <https://x.example/f/12|Ver>\n\n"
        "`ref` &amp; &lt;ok&gt;"
    )


def test_plain_and_html_formatting() -> None:
    assert (
        to_plain(MD)
        == "Factura 12\n\nHola Ana, vence el 30.\n\n• Importe: 120 €\n• Ver (https://x.example/f/12)\n\nref & <ok>"
    )
    html = to_html(MD + "\n\n```\nx < 1\n```")
    assert "<strong>Ana</strong>" in html and '<a href="https://x.example/f/12">Ver</a>' in html
    assert "&lt;ok&gt;" in html and "<pre" in html and "x &lt; 1" in html
    assert "<script>" not in to_html("<script>alert(1)</script>")


def test_split_text_prefers_boundaries_and_caps_parts() -> None:
    text = "\n\n".join(f"Párrafo {i}. " + "palabra " * 40 for i in range(10))
    parts = split_text(text, 500)
    assert all(len(p) <= 500 for p in parts)
    assert all(p.startswith("Párrafo") for p in parts)
    assert " ".join(parts).replace("\n", " ").split() == text.replace("\n", " ").split()
    capped = split_text("x" * 5000, 1000, max_parts=3)
    assert len(capped) == 3 and capped[-1].endswith("…") and all(len(p) <= 1000 for p in capped)
    assert split_text("  ", 100) == []
    assert single_line("a\n\nb    c", 100) == "a b c"
    with pytest.raises(ValueError):
        split_text("hola", 5)


def test_text_of_engine_outputs() -> None:
    assert text_of({"role": "assistant", "content": [{"type": "text", "text": "Hola"}, {"type": "tool_use"}]}) == "Hola"
    assert text_of("directo") == "directo"
    assert text_of(None) == ""


def test_notices_follow_locale_and_overrides() -> None:
    assert notice({}, "approval_pending").startswith("Tu solicitud")
    assert notice({"locale": "en"}, "error").startswith("Sorry")
    assert notice({"error_message": "Vuelve luego"}, "error") == "Vuelve luego"


def test_config_validation() -> None:
    whatsapp = get_adapter("whatsapp")
    cfg = whatsapp.normalize_config(
        {"phone_number_id": " 123 ", "template": {"name": "aviso_respuesta", "language": "es_ES"}, "locale": "en"}
    )
    assert cfg == {
        "locale": "en",
        "phone_number_id": "123",
        "template": {"name": "aviso_respuesta", "language": "es_ES", "body_parameter": True},
    }
    for bad in ({"locale": "fr"}, {"template": {"name": "Con Espacios"}}, {"api_version": "21"}):
        with pytest.raises(InvalidConfig):
            whatsapp.normalize_config(bad)
    assert get_adapter("email").normalize_config({"address_token": "forged"}) == {}


def test_email_normalization_and_loops() -> None:
    raw = {
        "From": "Clara <clara@cliente.example>",
        "FromFull": {"Email": "clara@cliente.example", "Name": "Clara"},
        "To": "ch-0123456789abcdef@in.messer.local",
        "Subject": "Hola",
        "TextBody": "Texto",
        "StrippedTextReply": "Solo lo nuevo",
        "MessageID": "abc",
        "Headers": [{"Name": "Message-ID", "Value": "<x@y>"}, {"Name": "Precedence", "Value": "bulk"}],
    }
    email = normalize(raw)
    assert email["from"] == "clara@cliente.example" and email["text"] == "Solo lo nuevo"
    assert email["message_id"] == "<x@y>" and is_auto_message(email)
    adapter = get_adapter("email")
    request = InboundRequest(method="POST", headers={}, query={}, body=b"[]")
    assert adapter.parse(None, request) == []  # type: ignore[arg-type]
