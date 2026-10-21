"""Default plan catalog (provisional prices, editable in /admin and synced to Stripe) and feature keys."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

UNLIMITED = -1

FEATURES = {
    "public_chat": "Chat público y widget",
    "api": "API pública y API keys",
    "connectors": "Conectores",
    "channels": "Canales (WhatsApp, Slack, Teams, email, Telegram)",
    "deployments": "Despliegue con un clic y entornos",
    "voice": "Voz (navegador y teléfono)",
    "sso": "SSO SAML/OIDC",
    "audit": "Registro de auditoría",
    "guard": "Guard: control de comportamiento",
    "priority_support": "Soporte prioritario",
    "eu_strict": "Residencia UE estricta (Bedrock UE)",
    "byoc": "Despliegue en tu nube",
    "scim": "SCIM",
    "sla": "SLA",
    "dedicated_engineer": "Ingeniero dedicado",
}

TRIAL_PLAN = "pro"
TRIAL_DAYS = 14

DEFAULT_PLANS: list[dict[str, Any]] = [
    {
        "id": "starter",
        "name": "Starter",
        "description": "Para empezar con un caso de uso.",
        "price_month_eur": Decimal("49"),
        "price_year_eur": Decimal("490"),
        "price_is_starting": False,
        "self_serve": True,
        "sort_order": 1,
        "limits": {
            "seats": 3,
            "projects": 1,
            "runs_month": 2000,
            "credits_month": 2000,
            "storage_gb": 5,
            "features": ["public_chat", "api"],
        },
    },
    {
        "id": "pro",
        "name": "Pro",
        "description": "Para equipos que llevan IA a producción.",
        "price_month_eur": Decimal("199"),
        "price_year_eur": Decimal("1990"),
        "price_is_starting": False,
        "self_serve": True,
        "sort_order": 2,
        "limits": {
            "seats": 10,
            "projects": 5,
            "runs_month": 20000,
            "credits_month": 10000,
            "storage_gb": 50,
            "features": ["public_chat", "api", "connectors", "channels", "deployments"],
        },
    },
    {
        "id": "business",
        "name": "Business",
        "description": "Para varias áreas de negocio con gobierno y voz.",
        "price_month_eur": Decimal("799"),
        "price_year_eur": Decimal("7990"),
        "price_is_starting": False,
        "self_serve": True,
        "sort_order": 3,
        "limits": {
            "seats": 25,
            "projects": UNLIMITED,
            "runs_month": 100000,
            "credits_month": 50000,
            "storage_gb": 250,
            "features": [
                "public_chat",
                "api",
                "connectors",
                "channels",
                "deployments",
                "voice",
                "sso",
                "audit",
                "guard",
                "priority_support",
            ],
        },
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "description": "Residencia UE estricta, tu nube, SCIM y SLA.",
        "price_month_eur": Decimal("3000"),
        "price_year_eur": Decimal("30000"),
        "price_is_starting": True,
        "self_serve": False,
        "sort_order": 4,
        "limits": {
            "seats": UNLIMITED,
            "projects": UNLIMITED,
            "runs_month": UNLIMITED,
            "credits_month": 300000,
            "storage_gb": 2000,
            "features": list(FEATURES.keys()),
        },
    },
]

CREDIT_PACKS: list[dict[str, Any]] = [
    {"id": "pack_5k", "credits": 5000, "price_eur": Decimal("55")},
    {"id": "pack_25k", "credits": 25000, "price_eur": Decimal("250")},
    {"id": "pack_100k", "credits": 100000, "price_eur": Decimal("900")},
]


def plan_has_feature(limits: dict[str, Any], feature: str) -> bool:
    return feature in (limits.get("features") or [])


def limit_value(limits: dict[str, Any], key: str) -> int:
    value = limits.get(key)
    return UNLIMITED if value is None else int(value)
