"""Herramientas del cualificador de leads: puntuación con los criterios comerciales y consulta de leads.

La puntuación sigue el documento «Criterios de cualificación de leads» (tamaño, presupuesto, plazo y sector) y
asigna el comercial del sector desde la tabla ``comerciales``. Los leads se leen de la tabla ``leads`` (en
producción, sincronízala desde tu CRM con un conector: HubSpot, Salesforce…).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from messer.core.tool import Tool
from messer.platform.tools import sql_query

KB_VENTAS = "${kb:ventas}"
SECTORES_OBJETIVO = ("industria", "logistica", "salud", "retail")
SECTORES = (*SECTORES_OBJETIVO, "hosteleria", "servicios", "educacion")
_SQL = sql_query(KB_VENTAS)


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def sector_de(texto: str) -> str:
    """El sector mencionado en un texto libre («Somos una empresa de logística…» → logistica)."""
    plano = _plano(texto)
    for sector in SECTORES:
        if sector[:6] in plano:
            return sector
    return "otros"


def puntuacion(empleados: int, presupuesto_eur: float, plazo_meses: int, sector: str) -> dict[str, Any]:
    empleados, presupuesto, plazo = int(empleados or 0), float(presupuesto_eur or 0), int(plazo_meses or 99)
    tam = 5 if empleados < 10 else 15 if empleados < 50 else 25 if empleados < 250 else 30
    pres = 0 if presupuesto < 3000 else 10 if presupuesto < 10000 else 20 if presupuesto < 30000 else 30
    plz = 25 if plazo <= 3 else 15 if plazo <= 6 else 5 if plazo <= 12 else 0
    sec = 15 if sector in SECTORES_OBJETIVO else 5
    total = tam + pres + plz + sec
    categoria = "caliente" if total >= 70 else "templado" if total >= 40 else "frio"
    return {
        "puntuacion": total,
        "categoria": categoria,
        "desglose": {"tamano": tam, "presupuesto": pres, "plazo": plz, "sector": sec},
    }


SIGUIENTE_PASO = {
    "caliente": "Responder en menos de 15 minutos proponiendo una demo con el comercial asignado",
    "templado": "Incluir en la secuencia de seguimiento y volver a puntuar cuando cambie su situación",
    "frio": "Responder con el plan Básico y la documentación, sin seguimiento comercial",
}


async def comercial_del_sector(sector: str) -> dict[str, Any]:
    result = await _SQL.handler(
        sql="SELECT nombre, email FROM comerciales WHERE sector = $1 OR sector = 'otros' "
        "ORDER BY (sector = $1) DESC LIMIT 1",
        params=[sector],
    )
    rows = result.get("rows") or []
    return {"nombre": rows[0][0], "email": rows[0][1]} if rows else {"nombre": "Dirección comercial", "email": ""}


async def _puntuar_lead(empleados: int, presupuesto_eur: float, plazo_meses: int, sector: str) -> dict[str, Any]:
    clave = sector_de(sector)
    resultado = puntuacion(empleados, presupuesto_eur, plazo_meses, clave)
    comercial = await comercial_del_sector(clave)
    return {
        **resultado,
        "sector": clave,
        "comercial": comercial["nombre"],
        "siguiente_paso": SIGUIENTE_PASO[resultado["categoria"]],
    }


async def _buscar_lead(email: str = "", empresa: str = "") -> dict[str, Any]:
    clave_email = str(email or "").strip().lower()
    clave_empresa = f"%{str(empresa or '').strip()}%" if empresa else ""
    result = await _SQL.handler(
        sql="SELECT empresa, nombre, email, sector, puntuacion, estado, comercial, fecha FROM leads "
        "WHERE lower(email) = $1 OR ($2 <> '' AND empresa ILIKE $2) ORDER BY fecha DESC LIMIT 5",
        params=[clave_email, clave_empresa],
    )
    columns = [c.get("name") if isinstance(c, dict) else str(c) for c in result.get("columns", [])]
    leads = [dict(zip(columns, row, strict=False)) for row in result.get("rows", [])]
    if not leads:
        return {"encontrado": False, "mensaje": "No hay ningún lead con esos datos."}
    return {"encontrado": True, "leads": leads}


puntuar_lead = Tool(
    name="puntuar_lead",
    description="Puntúa un lead de 0 a 100 con los criterios comerciales (empleados, presupuesto anual, plazo en "
    "meses y sector) y devuelve su categoría y el comercial asignado.",
    handler=_puntuar_lead,
)

buscar_lead = Tool(
    name="buscar_lead",
    description="Busca un lead por su email o empresa: estado, puntuación y comercial asignado.",
    handler=_buscar_lead,
)
