"""Transactional email templates (Spanish first, English second).

Each template has a subject, a list of paragraphs and optional buttons. Values are
rendered with Jinja2 (autoescaped) into one sober HTML layout and a plain-text part.
"""

from __future__ import annotations

from typing import Any, TypedDict

from jinja2 import Environment, StrictUndefined, select_autoescape

_env = Environment(autoescape=select_autoescape(default=True), undefined=StrictUndefined)


class _ButtonBase(TypedDict):
    label: str
    url: str


class Button(_ButtonBase, total=False):
    style: str  # primary | secondary | danger


class _TemplateBase(TypedDict):
    subject: str


class TemplateDef(_TemplateBase, total=False):
    paragraphs: list[str]
    buttons: list[Button]
    footer: str


TEMPLATES: dict[str, dict[str, TemplateDef]] = {
    "verify_email": {
        "es": {
            "subject": "Confirma tu email en Messer",
            "paragraphs": ["Hola {{ name }},", "Confirma tu dirección de email para activar tu cuenta."],
            "buttons": [{"label": "Confirmar email", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Confirm your email on Messer",
            "paragraphs": ["Hi {{ name }},", "Confirm your email address to activate your account."],
            "buttons": [{"label": "Confirm email", "url": "{{ url }}"}],
        },
    },
    "password_reset": {
        "es": {
            "subject": "Restablece tu contraseña",
            "paragraphs": [
                "Hemos recibido una solicitud para restablecer tu contraseña.",
                "El enlace caduca en 1 hora. Si no fuiste tú, ignora este email.",
            ],
            "buttons": [{"label": "Restablecer contraseña", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Reset your password",
            "paragraphs": [
                "We received a request to reset your password.",
                "The link expires in 1 hour. If it wasn't you, ignore this email.",
            ],
            "buttons": [{"label": "Reset password", "url": "{{ url }}"}],
        },
    },
    "invitation": {
        "es": {
            "subject": "{{ inviter }} te invita a {{ org }} en Messer",
            "paragraphs": ["{{ inviter }} te ha invitado a unirte a {{ org }} con el rol {{ role }}."],
            "buttons": [{"label": "Aceptar invitación", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "{{ inviter }} invited you to {{ org }} on Messer",
            "paragraphs": ["{{ inviter }} invited you to join {{ org }} as {{ role }}."],
            "buttons": [{"label": "Accept invitation", "url": "{{ url }}"}],
        },
    },
    "trial_day_1": {
        "es": {
            "subject": "Bienvenido a Messer: tu primer agente en 10 minutos",
            "paragraphs": [
                "Hola {{ name }}, tu prueba de 14 días del plan Pro ya está activa.",
                "Describe un problema en el Composer y Messer construirá la solución completa.",
            ],
            "buttons": [{"label": "Abrir Messer", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Welcome to Messer: your first agent in 10 minutes",
            "paragraphs": [
                "Hi {{ name }}, your 14-day Pro trial is active.",
                "Describe a problem in the Composer and Messer will build the complete solution.",
            ],
            "buttons": [{"label": "Open Messer", "url": "{{ url }}"}],
        },
    },
    "trial_day_3": {
        "es": {
            "subject": "Conecta tus datos a Messer",
            "paragraphs": [
                "Tus agentes rinden mejor con tus documentos y tablas.",
                "Sube PDFs, un CSV o conecta Google Drive, SharePoint o tu base de datos.",
            ],
            "buttons": [{"label": "Conectar datos", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Connect your data to Messer",
            "paragraphs": [
                "Your agents perform better with your documents and tables.",
                "Upload PDFs, a CSV, or connect Google Drive, SharePoint or your database.",
            ],
            "buttons": [{"label": "Connect data", "url": "{{ url }}"}],
        },
    },
    "trial_day_7": {
        "es": {
            "subject": "Lleva tu agente a producción",
            "paragraphs": [
                "Publica con un clic: entornos, versiones y evals como puerta de calidad.",
                "Añade WhatsApp, Slack o voz sin reconstruir nada.",
            ],
            "buttons": [{"label": "Ver despliegues", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Take your agent to production",
            "paragraphs": [
                "Publish in one click: environments, versions and evals as a quality gate.",
                "Add WhatsApp, Slack or voice without rebuilding anything.",
            ],
            "buttons": [{"label": "See deployments", "url": "{{ url }}"}],
        },
    },
    "trial_day_12": {
        "es": {
            "subject": "Tu prueba termina en 2 días",
            "paragraphs": [
                "Tu prueba del plan Pro termina el {{ trial_end }}.",
                "Elige un plan para mantener tus proyectos activos. Pro cuesta {{ pro_price }} al mes.",
            ],
            "buttons": [{"label": "Elegir plan", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Your trial ends in 2 days",
            "paragraphs": [
                "Your Pro trial ends on {{ trial_end }}.",
                "Choose a plan to keep your projects running. Pro costs {{ pro_price }} per month.",
            ],
            "buttons": [{"label": "Choose a plan", "url": "{{ url }}"}],
        },
    },
    "approval_request": {
        "es": {
            "subject": "Aprobación pendiente: {{ title }}",
            "paragraphs": [
                "{{ workforce }} necesita tu aprobación en {{ project }}.",
                "Acción: {{ tool }}",
                "{{ summary }}",
            ],
            "buttons": [
                {"label": "Aprobar", "url": "{{ approve_url }}", "style": "primary"},
                {"label": "Denegar", "url": "{{ deny_url }}", "style": "danger"},
                {"label": "Ver en Messer", "url": "{{ url }}", "style": "secondary"},
            ],
            "footer": "Los enlaces son de un solo uso y caducan el {{ expires }}.",
        },
        "en": {
            "subject": "Approval needed: {{ title }}",
            "paragraphs": [
                "{{ workforce }} needs your approval in {{ project }}.",
                "Action: {{ tool }}",
                "{{ summary }}",
            ],
            "buttons": [
                {"label": "Approve", "url": "{{ approve_url }}", "style": "primary"},
                {"label": "Deny", "url": "{{ deny_url }}", "style": "danger"},
                {"label": "View in Messer", "url": "{{ url }}", "style": "secondary"},
            ],
            "footer": "Links are single-use and expire on {{ expires }}.",
        },
    },
    "budget_alert": {
        "es": {
            "subject": "Presupuesto al {{ pct }}%: {{ scope }}",
            "paragraphs": ["Has consumido {{ spent }} de {{ limit }} ({{ pct }}%) este periodo en {{ scope }}."],
            "buttons": [{"label": "Revisar presupuestos", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Budget at {{ pct }}%: {{ scope }}",
            "paragraphs": ["You have spent {{ spent }} of {{ limit }} ({{ pct }}%) this period on {{ scope }}."],
            "buttons": [{"label": "Review budgets", "url": "{{ url }}"}],
        },
    },
    "alarm_fired": {
        "es": {
            "subject": "Alarma: {{ alarm }}",
            "paragraphs": ["La métrica {{ metric }} vale {{ value }} (umbral {{ comparator }} {{ threshold }})."],
            "buttons": [{"label": "Ver analítica", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Alarm: {{ alarm }}",
            "paragraphs": ["Metric {{ metric }} is {{ value }} (threshold {{ comparator }} {{ threshold }})."],
            "buttons": [{"label": "View analytics", "url": "{{ url }}"}],
        },
    },
    "deployment_failed": {
        "es": {
            "subject": "Despliegue fallido en {{ project }}",
            "paragraphs": ["El despliegue a {{ environment }} ha fallado: {{ reason }}"],
            "buttons": [{"label": "Ver despliegue", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Deployment failed in {{ project }}",
            "paragraphs": ["The deployment to {{ environment }} failed: {{ reason }}"],
            "buttons": [{"label": "View deployment", "url": "{{ url }}"}],
        },
    },
    "service_down": {
        "es": {
            "subject": "Servicio degradado: {{ service }}",
            "paragraphs": ["El servicio {{ service }} no responde correctamente: {{ detail }}"],
            "buttons": [{"label": "Página de estado", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Service degraded: {{ service }}",
            "paragraphs": ["Service {{ service }} is not responding correctly: {{ detail }}"],
            "buttons": [{"label": "Status page", "url": "{{ url }}"}],
        },
    },
    "data_export_ready": {
        "es": {
            "subject": "Tu exportación de datos está lista",
            "paragraphs": ["La exportación solicitada está lista para descargar durante 7 días."],
            "buttons": [{"label": "Descargar", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "Your data export is ready",
            "paragraphs": ["The export you requested is ready to download for 7 days."],
            "buttons": [{"label": "Download", "url": "{{ url }}"}],
        },
    },
    "payment_failed": {
        "es": {
            "subject": "No hemos podido cobrar tu suscripción",
            "paragraphs": [
                "El último pago de {{ org }} ha fallado.",
                "Actualiza tu método de pago antes del {{ grace_end }} para evitar el modo solo lectura.",
            ],
            "buttons": [{"label": "Actualizar pago", "url": "{{ url }}"}],
        },
        "en": {
            "subject": "We couldn't charge your subscription",
            "paragraphs": [
                "The latest payment for {{ org }} failed.",
                "Update your payment method before {{ grace_end }} to avoid read-only mode.",
            ],
            "buttons": [{"label": "Update payment", "url": "{{ url }}"}],
        },
    },
    "contact_received": {
        "es": {
            "subject": "Nuevo contacto: {{ name }} ({{ company }})",
            "paragraphs": ["{{ name }} <{{ email }}> escribe sobre {{ topic }}:", "{{ message }}"],
        },
        "en": {
            "subject": "New contact: {{ name }} ({{ company }})",
            "paragraphs": ["{{ name }} <{{ email }}> writes about {{ topic }}:", "{{ message }}"],
        },
    },
    "generic": {
        "es": {"subject": "{{ subject }}", "paragraphs": ["{{ body }}"]},
        "en": {"subject": "{{ subject }}", "paragraphs": ["{{ body }}"]},
    },
}

_LAYOUT = _env.from_string(
    """<!doctype html>
<html lang="{{ locale }}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{{ subject }}</title></head>
<body style="margin:0;padding:0;background:#f6f5f3;font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif;color:#111">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 12px">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0"
 style="max-width:560px;width:100%;background:#fff;border:1px solid #e7e5e1;border-radius:8px">
<tr><td style="padding:24px 28px;border-bottom:1px solid #e7e5e1;font-weight:600;font-size:16px">
<span style="display:inline-block;width:10px;height:10px;background:#D52B1E;margin-right:8px"></span>Messer</td></tr>
<tr><td style="padding:24px 28px;font-size:14px;line-height:1.6">
{% for p in paragraphs %}<p style="margin:0 0 14px">{{ p }}</p>{% endfor %}
{% if buttons %}<p style="margin:20px 0 4px">{% for b in buttons %}
<a href="{{ b.url }}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;
{% if b.style == 'danger' %}background:#fff;color:#b42318;border:1px solid #f1c3be{% elif b.style == 'secondary' %}background:#fff;color:#111;border:1px solid #e7e5e1{% else %}background:#D52B1E;color:#fff;border:1px solid #D52B1E{% endif %}">{{ b.label }}</a>
{% endfor %}</p>{% endif %}
{% if footer %}<p style="margin:16px 0 0;color:#6b6760;font-size:13px">{{ footer }}</p>{% endif %}
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #e7e5e1;color:#6b6760;font-size:12px">
Messer · {{ footer_line }}</td></tr>
</table></td></tr></table></body></html>"""
)


def render_email(template: str, context: dict[str, Any], locale: str = "es") -> tuple[str, str, str]:
    """Return (subject, html, text) for a template in the requested locale (es fallback)."""
    if template not in TEMPLATES:
        raise KeyError(f"unknown email template {template}")
    variants = TEMPLATES[template]
    tpl = variants.get(locale) or variants["es"]
    ctx = dict(context)

    def r(s: str) -> str:
        return _env.from_string(s).render(**ctx)

    subject = r(tpl["subject"])
    paragraphs = [r(p) for p in tpl.get("paragraphs", [])]
    buttons = [
        {"label": r(b["label"]), "url": r(b["url"]), "style": b.get("style", "primary")} for b in tpl.get("buttons", [])
    ]
    footer_tpl = tpl.get("footer")
    footer = r(footer_tpl) if footer_tpl else ""
    footer_line = "Infraestructura en la UE" if locale == "es" else "EU infrastructure"
    html = _LAYOUT.render(
        locale=locale, subject=subject, paragraphs=paragraphs, buttons=buttons, footer=footer, footer_line=footer_line
    )
    text_lines = [*paragraphs, ""]
    text_lines += [f"{b['label']}: {b['url']}" for b in buttons]
    if footer:
        text_lines += ["", footer]
    return subject, html, "\n".join(text_lines).strip() + "\n"
