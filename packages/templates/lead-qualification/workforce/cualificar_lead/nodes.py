"""Nodos propios del flujo de cualificación: puntuación con los criterios comerciales y asignación del comercial.

Las mismas reglas que usa el agente cualificador (documento «Criterios de cualificación de leads»).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from messer.platform.tools import sql_query

KB_VENTAS = "${kb:ventas}"
SECTORES_OBJETIVO = ("industria", "logistica", "salud", "retail")
SECTORES = (*SECTORES_OBJETIVO, "hosteleria", "servicios", "educacion")
_SQL = sql_query(KB_VENTAS)
SIGUIENTE_PASO = {
    "caliente": "Responder en menos de 15 minutos proponiendo una demo con el comercial asignado",
    "templado": "Incluir en la secuencia de seguimiento y volver a puntuar cuando cambie su situación",
    "frio": "Responder con el plan Básico y la documentación, sin seguimiento comercial",
}


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


async def puntuar_lead(
    empresa: str = "",
    sector: str = "",
    empleados: float | None = None,
    presupuesto_eur: float | None = None,
    plazo_meses: float | None = None,
) -> dict[str, Any]:
    """Puntúa el lead (0–100), decide su categoría y busca el comercial de su sector."""
    plano = _plano(sector)
    clave = next((s for s in SECTORES if s[:6] in plano), "otros")
    emp, pres, plazo = int(empleados or 0), float(presupuesto_eur or 0), int(plazo_meses or 99)
    puntos = {
        "tamano": 5 if emp < 10 else 15 if emp < 50 else 25 if emp < 250 else 30,
        "presupuesto": 0 if pres < 3000 else 10 if pres < 10000 else 20 if pres < 30000 else 30,
        "plazo": 25 if plazo <= 3 else 15 if plazo <= 6 else 5 if plazo <= 12 else 0,
        "sector": 15 if clave in SECTORES_OBJETIVO else 5,
    }
    total = sum(puntos.values())
    categoria = "caliente" if total >= 70 else "templado" if total >= 40 else "frio"
    result = await _SQL.handler(
        sql="SELECT nombre, email FROM comerciales WHERE sector = $1 OR sector = 'otros' "
        "ORDER BY (sector = $1) DESC LIMIT 1",
        params=[clave],
    )
    rows = result.get("rows") or []
    return {
        "empresa": empresa,
        "sector": clave,
        "puntuacion": total,
        "categoria": categoria,
        "desglose": puntos,
        "comercial": rows[0][0] if rows else "Dirección comercial",
        "email_comercial": rows[0][1] if rows else "",
        "siguiente_paso": SIGUIENTE_PASO[categoria],
    }
