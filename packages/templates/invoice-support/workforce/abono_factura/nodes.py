"""Nodos propios del flujo de abonos: validación de la solicitud contra la tabla de facturas y emisión.

Cada función pública aparece en la paleta del lienzo como nodo personalizado. Leen la tabla ``facturas`` de la
base de conocimiento «Facturación» con SQL de solo lectura.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from messer.platform.tools import sql_query

KB_FACTURACION = "${kb:facturacion}"
UMBRAL_APROBACION_EUR = Decimal("500")
_SQL = sql_query(KB_FACTURACION)


def _importe(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _eur(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


async def validar_abono(numero_factura: str = "", importe: float = 0, motivo: str = "") -> dict[str, Any]:
    """Comprueba que la factura existe, que no está abonada y que el abono no supera su importe."""
    result = await _SQL.handler(
        sql="SELECT numero, cliente, importe, estado FROM facturas WHERE upper(numero) = upper($1)",
        params=[str(numero_factura or "").strip()],
    )
    rows = result.get("rows") or []
    solicitado = _importe(importe)
    base: dict[str, Any] = {
        "numero_factura": str(numero_factura or "").strip().upper(),
        "importe": float(solicitado),
        "motivo": str(motivo or "").strip() or "Sin motivo indicado",
        "cliente": None,
        "importe_factura": None,
    }
    if not rows:
        return {**base, "valido": False, "requiere_aprobacion": False, "error": "La factura no existe"}
    numero, cliente, total, estado = rows[0][0], rows[0][1], _importe(rows[0][2]), rows[0][3]
    base.update(numero_factura=numero, cliente=cliente, importe_factura=float(total))
    if estado == "abonada":
        error = "La factura ya está abonada"
    elif solicitado <= 0:
        error = "El importe debe ser mayor que cero"
    elif solicitado > total:
        error = f"El abono supera el importe de la factura ({_eur(total)})"
    else:
        error = None
    return {
        **base,
        "valido": error is None,
        "requiere_aprobacion": error is None and solicitado > UMBRAL_APROBACION_EUR,
        "error": error,
    }


def emitir_abono(
    numero_factura: str = "",
    importe: float = 0,
    importe_aprobado: float | None = None,
    motivo: str = "",
    cliente: str = "",
    valido: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    """Emite el abono validado (con el importe corregido por el aprobador, si lo cambió)."""
    if not valido:
        return {"emitido": False, "factura": numero_factura, "motivo_rechazo": error or "Solicitud no válida"}
    final = _importe(importe_aprobado if importe_aprobado is not None else importe)
    digest = hashlib.sha256(f"{numero_factura}|{final}|{motivo}".encode()).hexdigest()[:4].upper()
    return {
        "emitido": True,
        "abono": f"AB-{str(numero_factura).removeprefix('F-')}-{digest}",
        "factura": numero_factura,
        "cliente": cliente,
        "importe": float(final),
        "importe_texto": _eur(final),
        "motivo": motivo,
        "aprobacion": "aprobado" if importe_aprobado is not None else "no necesaria",
    }
