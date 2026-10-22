"""Herramientas del asistente de facturas: consulta de facturas y emisión de abonos.

Leen la tabla ``facturas`` de la base de conocimiento «Facturación» del proyecto con SQL de solo lectura (con
parámetros, nunca texto interpolado). Los abonos de más de ``UMBRAL_APROBACION_EUR`` euros esperan la aprobación de
un administrador antes de emitirse; los demás se emiten al momento.

Esta versión de ejemplo genera el número de abono y devuelve el documento. Para registrarlo en tu ERP, sustituye
``_registrar_abono`` por la acción de tu conector (Holded, SAP, una base de datos…).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from messer.core.tool import Tool
from messer.platform.tools import sql_query

KB_FACTURACION = "${kb:facturacion}"
UMBRAL_APROBACION_EUR = 500.0
_SQL = sql_query(KB_FACTURACION)
_COLUMNAS = "numero, cliente, concepto, fecha_emision, fecha_vencimiento, importe, estado"


def _eur(value: Any) -> str:
    """1452.5 → «1.452,50 €»."""
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    text = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


def _numero(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


async def _filas(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    result = await _SQL.handler(sql=sql, params=params)
    columns = [c.get("name") if isinstance(c, dict) else str(c) for c in result.get("columns", [])]
    return [dict(zip(columns, row, strict=False)) for row in result.get("rows", [])]


def _ficha(fila: dict[str, Any]) -> dict[str, Any]:
    return {
        "numero": fila["numero"],
        "cliente": fila["cliente"],
        "concepto": fila["concepto"],
        "emitida": str(fila["fecha_emision"]),
        "vence": str(fila["fecha_vencimiento"]),
        "importe": _eur(fila["importe"]),
        "estado": fila["estado"],
    }


async def _buscar(numero_factura: str) -> dict[str, Any] | None:
    filas = await _filas(
        f"SELECT {_COLUMNAS} FROM facturas WHERE upper(numero) = upper($1)", [str(numero_factura).strip()]
    )
    return filas[0] if filas else None


async def _consultar_factura(numero_factura: str) -> dict[str, Any]:
    fila = await _buscar(numero_factura)
    if fila is None:
        return {"encontrada": False, "mensaje": f"No existe ninguna factura con el número {numero_factura}."}
    return {"encontrada": True, **_ficha(fila)}


async def _facturas_pendientes(cliente: str = "") -> dict[str, Any]:
    filtro = f"%{cliente.strip()}%" if cliente and cliente.strip() else "%"
    filas = await _filas(
        f"SELECT {_COLUMNAS} FROM facturas WHERE estado IN ('pendiente', 'vencida') AND cliente ILIKE $1 "
        "ORDER BY fecha_vencimiento LIMIT 25",
        [filtro],
    )
    total = sum((_numero(f["importe"]) for f in filas), Decimal(0))
    return {
        "total_facturas": len(filas),
        "importe_total": _eur(total),
        "vencidas": sum(1 for f in filas if f["estado"] == "vencida"),
        "facturas": [
            {"numero": f["numero"], "cliente": f["cliente"], "importe": _eur(f["importe"]), "estado": f["estado"]}
            for f in filas[:10]
        ],
    }


def _registrar_abono(numero_factura: str, importe: Decimal, motivo: str) -> str:
    """Número del abono (determinista para la misma solicitud). Conecta aquí tu ERP."""
    digest = hashlib.sha256(f"{numero_factura}|{importe}|{motivo}".encode()).hexdigest()[:4].upper()
    return f"AB-{numero_factura.removeprefix('F-')}-{digest}"


async def _emitir_abono(numero_factura: str, importe: float, motivo: str) -> dict[str, Any]:
    fila = await _buscar(numero_factura)
    if fila is None:
        return {"emitido": False, "motivo_rechazo": f"No existe ninguna factura con el número {numero_factura}."}
    solicitado = _numero(importe).quantize(Decimal("0.01"))
    total = _numero(fila["importe"])
    if fila["estado"] == "abonada":
        return {"emitido": False, "motivo_rechazo": f"La factura {fila['numero']} ya está abonada."}
    if solicitado <= 0:
        return {"emitido": False, "motivo_rechazo": "El importe del abono debe ser mayor que cero."}
    if solicitado > total:
        return {
            "emitido": False,
            "motivo_rechazo": f"El abono ({_eur(solicitado)}) supera el importe de la factura ({_eur(total)}).",
        }
    return {
        "emitido": True,
        "abono": _registrar_abono(fila["numero"], solicitado, motivo),
        "factura": fila["numero"],
        "cliente": fila["cliente"],
        "importe": _eur(solicitado),
        "motivo": motivo,
        "aprobacion": "aprobado por un responsable" if solicitado > Decimal(str(UMBRAL_APROBACION_EUR)) else "no necesaria",
        "plazo": "El abono se emite en un máximo de 5 días hábiles y se reembolsa en 10 días hábiles.",
    }


def _requiere_aprobacion(numero_factura: str, importe: float, motivo: str = "") -> dict[str, Any]:
    if float(importe) <= UMBRAL_APROBACION_EUR:
        return {"required": False}
    return {
        "required": True,
        "prompt": f"¿Emitir un abono de {_eur(importe)} sobre la factura {numero_factura}? Motivo: {motivo or '—'}",
        "grantable": False,
    }


consultar_factura = Tool(
    name="consultar_factura",
    description="Consulta una factura por su número: cliente, importe, vencimiento y si está pagada.",
    handler=_consultar_factura,
)

facturas_pendientes = Tool(
    name="facturas_pendientes",
    description="Lista las facturas pendientes de cobro o vencidas, opcionalmente de un cliente.",
    handler=_facturas_pendientes,
)

emitir_abono = Tool(
    name="emitir_abono",
    description=(
        "Emite un abono (rectificativa) sobre una factura con su importe y motivo. "
        f"Por encima de {UMBRAL_APROBACION_EUR:.0f} € espera la aprobación de un responsable."
    ),
    handler=_emitir_abono,
    requires_approval=_requiere_aprobacion,
    approval_grantable=False,
)
