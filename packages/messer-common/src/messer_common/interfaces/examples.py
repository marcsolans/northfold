"""Interface templates and documented examples (used by the API, the editor and the Composer's playbook).

Builders return plain dicts that :func:`validate_interface` accepts. ``EXAMPLES`` uses a placeholder
knowledge base id; real templates are built with the project's own ids.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..knowledge.sqlcheck import quote_ident

PLACEHOLDER_KB = "00000000-0000-4000-8000-000000000000"

NUMERIC_TYPES = {"integer", "numeric", "bigint", "int", "int4", "int8", "float", "double", "real", "decimal"}
DATE_TYPES = {"date", "timestamp", "timestamptz", "datetime"}


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    key: str
    kind: str
    name: str
    name_en: str
    description: str
    description_en: str
    requires: tuple[str, ...]  # "kb_id", "table", "agent"


TEMPLATES: tuple[TemplateInfo, ...] = (
    TemplateInfo(
        key="blank_app",
        kind="app",
        name="Panel en blanco",
        name_en="Blank dashboard",
        description="Una pantalla vacía para componer desde cero.",
        description_en="An empty screen to compose from scratch.",
        requires=(),
    ),
    TemplateInfo(
        key="table_dashboard",
        kind="app",
        name="Panel sobre una tabla",
        name_en="Table dashboard",
        description="KPI con el total de filas, la tabla completa y un gráfico si hay columnas numéricas.",
        description_en="Row-count KPI, the full table and a chart when there are numeric columns.",
        requires=("kb_id", "table"),
    ),
    TemplateInfo(
        key="invoices_dashboard",
        kind="app",
        name="Panel de facturas",
        name_en="Invoices dashboard",
        description="Facturas pendientes, importe pendiente, vencidas y evolución mensual "
        "(tabla con numero, cliente, importe, estado, fecha_emision, fecha_vencimiento).",
        description_en="Pending invoices, pending amount, overdue and monthly trend "
        "(table with numero, cliente, importe, estado, fecha_emision, fecha_vencimiento).",
        requires=("kb_id",),
    ),
    TemplateInfo(
        key="public_chat",
        kind="chat",
        name="Chat público",
        name_en="Public chat",
        description="Página de chat con tu agente, con tema configurable y widget para tu web.",
        description_en="Chat page with your agent, configurable theme and a widget for your website.",
        requires=("agent",),
    ),
)


def template_info(key: str) -> TemplateInfo | None:
    return next((t for t in TEMPLATES if t.key == key), None)


def _grid(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h}


def blank_app(*, name: str, slug: str) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        "slug": slug,
        "kind": "app",
        "auth": {"required": True, "roles": []},
        "screens": [{"id": "inicio", "title": "Inicio", "layout": "grid", "components": []}],
    }


def public_chat(*, name: str, slug: str, agent: str, greeting: str | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        "slug": slug,
        "kind": "chat",
        "auth": {"required": False, "roles": []},
        "screens": [
            {
                "id": "chat",
                "title": name,
                "layout": "grid",
                "components": [
                    {
                        "id": "chat",
                        "type": "chat",
                        "title": name,
                        "grid": _grid(0, 0, 12, 12),
                        "props": {
                            "greeting": greeting or "Hola, ¿en qué puedo ayudarte?",
                            "placeholder": "Escribe tu pregunta…",
                            "suggestions": [],
                        },
                        "binding": {"kind": "agent", "workforce": agent},
                    }
                ],
            }
        ],
    }


def invoices_dashboard(
    *, name: str, slug: str, kb_id: str, table: str = "facturas", agent: str | None = None
) -> dict[str, Any]:
    """The demo dashboard: pending invoices (KPIs + table) and the monthly trend over an invoices table."""
    t = quote_ident(table)
    pending = "estado = $1"
    components: list[dict[str, Any]] = [
        {
            "id": "kpi_pendientes",
            "type": "kpi",
            "title": "Facturas pendientes",
            "grid": _grid(0, 0, 4, 3),
            "props": {"value": "total", "format": "number", "hint": "Pendientes de cobro"},
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT count(*) AS total FROM {t} WHERE {pending}",
                "params": ["pendiente"],
            },
        },
        {
            "id": "kpi_importe",
            "type": "kpi",
            "title": "Importe pendiente",
            "grid": _grid(4, 0, 4, 3),
            "props": {"value": "importe", "format": "currency", "currency": "EUR", "decimals": 2},
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT coalesce(sum(importe), 0) AS importe FROM {t} WHERE {pending}",
                "params": ["pendiente"],
            },
        },
        {
            "id": "kpi_vencidas",
            "type": "kpi",
            "title": "Vencidas",
            "grid": _grid(8, 0, 4, 3),
            "props": {"value": "total", "format": "number", "trend": "down_is_good", "hint": "Vencimiento superado"},
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT count(*) AS total FROM {t} WHERE {pending} AND fecha_vencimiento < $2",
                "params": ["pendiente", {"context": "today"}],
            },
        },
        {
            "id": "tabla_pendientes",
            "type": "data_table",
            "title": "Facturas pendientes",
            "grid": _grid(0, 3, 7, 8),
            "props": {
                "columns": [
                    {"key": "numero", "label": "Número"},
                    {"key": "cliente", "label": "Cliente"},
                    {"key": "importe", "label": "Importe", "format": "currency", "align": "right"},
                    {"key": "fecha_vencimiento", "label": "Vence", "format": "date"},
                    {"key": "estado", "label": "Estado", "format": "badge"},
                ],
                "page_size": 10,
                "searchable": True,
                "filters": [
                    {
                        "name": "estado",
                        "label": "Estado",
                        "type": "select",
                        "options": [
                            {"value": "pendiente", "label": "Pendiente"},
                            {"value": "pagada", "label": "Pagada"},
                        ],
                        "default": "pendiente",
                    }
                ],
                "empty_text": "No hay facturas pendientes",
            },
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT numero, cliente, importe, fecha_vencimiento, estado FROM {t} "
                "WHERE estado = $1 ORDER BY fecha_vencimiento",
                "params": [{"input": "estado", "default": "pendiente"}],
            },
        },
        {
            "id": "grafico_mensual",
            "type": "chart",
            "title": "Facturado por mes",
            "grid": _grid(7, 3, 5, 8),
            "props": {"chart": "bar", "x": "mes", "y": ["importe"], "format": "currency", "legend": False},
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT to_char(date_trunc('month', fecha_emision), 'YYYY-MM') AS mes, sum(importe) AS importe "
                f"FROM {t} GROUP BY 1 ORDER BY 1",
                "params": [],
            },
        },
    ]
    if agent:
        components.append(
            {
                "id": "asistente",
                "type": "chat",
                "title": "Pregunta al asistente",
                "grid": _grid(0, 11, 12, 8),
                "props": {"greeting": "Pregúntame por cualquier factura.", "suggestions": []},
                "binding": {"kind": "agent", "workforce": agent},
            }
        )
    return {
        "version": 1,
        "name": name,
        "slug": slug,
        "kind": "app",
        "description": "Facturas pendientes y evolución mensual",
        "auth": {"required": True, "roles": []},
        "screens": [{"id": "resumen", "title": "Resumen", "layout": "grid", "components": components}],
    }


def table_dashboard(*, name: str, slug: str, kb_id: str, table: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Generic dashboard over any knowledge base table (``columns``: ``[{"name", "type"}]``)."""
    t = quote_ident(table)
    names = [str(c["name"]) for c in columns if not str(c["name"]).startswith("_")]
    numeric = [str(c["name"]) for c in columns if str(c.get("type", "")).lower() in NUMERIC_TYPES]
    dates = [str(c["name"]) for c in columns if str(c.get("type", "")).lower() in DATE_TYPES]
    text_cols = [n for n in names if n not in numeric and n not in dates]
    components: list[dict[str, Any]] = [
        {
            "id": "kpi_total",
            "type": "kpi",
            "title": "Registros",
            "grid": _grid(0, 0, 4, 3),
            "props": {"value": "total", "format": "number", "hint": table},
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT count(*) AS total FROM {t}",
                "params": [],
            },
        }
    ]
    if numeric:
        col = numeric[0]
        components.append(
            {
                "id": "kpi_suma",
                "type": "kpi",
                "title": f"Total {col}",
                "grid": _grid(4, 0, 4, 3),
                "props": {"value": "total", "format": "number", "decimals": 2},
                "binding": {
                    "kind": "knowledge_sql",
                    "kb_id": kb_id,
                    "sql": f"SELECT coalesce(sum({quote_ident(col)}), 0) AS total FROM {t}",
                    "params": [],
                },
            }
        )
    order = f" ORDER BY {quote_ident(dates[0])} DESC" if dates else ""
    shown = names[:12]
    select_cols = ", ".join(quote_ident(n) for n in shown) or "*"
    components.append(
        {
            "id": "tabla",
            "type": "data_table",
            "title": table,
            "grid": _grid(0, 3, 12 if not (numeric and (text_cols or dates)) else 7, 8),
            "props": {
                "columns": [
                    {
                        "key": n,
                        "format": "number" if n in numeric else ("date" if n in dates else "text"),
                        **({"align": "right"} if n in numeric else {}),
                    }
                    for n in shown
                ],
                "page_size": 10,
                "searchable": True,
            },
            "binding": {
                "kind": "knowledge_sql",
                "kb_id": kb_id,
                "sql": f"SELECT {select_cols} FROM {t}{order}",
                "params": [],
            },
        }
    )
    if numeric and (text_cols or dates):
        group = text_cols[0] if text_cols else dates[0]
        value = numeric[0]
        components.append(
            {
                "id": "grafico",
                "type": "chart",
                "title": f"{value} por {group}",
                "grid": _grid(7, 3, 5, 8),
                "props": {"chart": "bar", "x": group, "y": [value], "legend": False},
                "binding": {
                    "kind": "knowledge_sql",
                    "kb_id": kb_id,
                    "sql": f"SELECT {quote_ident(group)}::text AS {quote_ident(group)}, sum({quote_ident(value)}) AS "
                    f"{quote_ident(value)} FROM {t} GROUP BY 1 ORDER BY 2 DESC LIMIT 12",
                    "params": [],
                },
            }
        )
    return {
        "version": 1,
        "name": name,
        "slug": slug,
        "kind": "app",
        "auth": {"required": True, "roles": []},
        "screens": [{"id": "resumen", "title": "Resumen", "layout": "grid", "components": components}],
    }


def request_form(*, name: str, slug: str, workflow: str) -> dict[str, Any]:
    """A form that starts a workflow (credit-note request) next to the approvals inbox."""
    return {
        "version": 1,
        "name": name,
        "slug": slug,
        "kind": "app",
        "auth": {"required": True, "roles": []},
        "screens": [
            {
                "id": "solicitudes",
                "title": "Solicitudes",
                "layout": "grid",
                "components": [
                    {
                        "id": "formulario",
                        "type": "form",
                        "title": "Solicitar abono",
                        "grid": _grid(0, 0, 6, 9),
                        "props": {
                            "fields": [
                                {"name": "factura", "label": "Número de factura", "required": True},
                                {
                                    "name": "importe",
                                    "label": "Importe (€)",
                                    "type": "number",
                                    "required": True,
                                    "min": 0,
                                },
                                {"name": "motivo", "label": "Motivo", "type": "textarea"},
                            ],
                            "submit_label": "Enviar solicitud",
                            "success_message": "Solicitud enviada",
                        },
                        "binding": {
                            "kind": "workflow",
                            "workforce": workflow,
                            "input_mapping": {
                                "factura": "$form.factura",
                                "importe": "$form.importe",
                                "motivo": "$form.motivo",
                                "solicitante": "$user.email",
                            },
                        },
                    },
                    {
                        "id": "aprobaciones",
                        "type": "approvals_inbox",
                        "title": "Pendientes de aprobación",
                        "grid": _grid(6, 0, 6, 9),
                        "props": {"page_size": 10},
                        "binding": {"kind": "approvals", "project": "current", "status": "pending"},
                    },
                ],
            }
        ],
    }


EXAMPLES: dict[str, dict[str, Any]] = {
    "invoices_dashboard": invoices_dashboard(
        name="Panel de facturas", slug="panel-facturas", kb_id=PLACEHOLDER_KB, agent="soporte"
    ),
    "public_chat": public_chat(name="Asistente de facturas", slug="chat-soporte", agent="soporte"),
    "request_form": request_form(name="Solicitudes de abono", slug="solicitudes", workflow="nota_credito"),
}


def build_template(
    key: str,
    *,
    name: str,
    slug: str,
    kb_id: uuid.UUID | str | None = None,
    table: str | None = None,
    columns: list[dict[str, Any]] | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    """Definition for a template key. Raises ``ValueError`` (Spanish message) when a parameter is missing."""
    if key == "blank_app":
        return blank_app(name=name, slug=slug)
    if key == "public_chat":
        if not agent:
            raise ValueError("Elige el agente del chat")
        return public_chat(name=name, slug=slug, agent=agent)
    if key == "invoices_dashboard":
        if not kb_id:
            raise ValueError("Elige la base de conocimiento con la tabla de facturas")
        return invoices_dashboard(name=name, slug=slug, kb_id=str(kb_id), table=table or "facturas", agent=agent)
    if key == "table_dashboard":
        if not kb_id or not table:
            raise ValueError("Elige la base de conocimiento y la tabla")
        return table_dashboard(name=name, slug=slug, kb_id=str(kb_id), table=table, columns=columns or [])
    raise ValueError(f"Plantilla desconocida «{key}»")
