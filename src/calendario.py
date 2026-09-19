"""
calendario.py - Proximas publicaciones macro con fechas REALES.

Por que existe este modulo: el bloque "que vigilar" del PDF debe traer fechas
verificables. Un modelo de lenguaje inventa fechas con total soltura, asi que
las fechas NUNCA salen de la IA: salen de aqui.

Dos fuentes:
  - Calculadas: las que siguen una regla fija (NFP = primer viernes del mes,
    solicitudes de desempleo = todos los jueves).
  - Tabuladas: las que publica cada organismo con un calendario anual
    (FOMC y CPI). Se copian de la fuente oficial y llevan fecha de vigencia:
    pasada esa fecha el modulo lo dice en vez de inventar.

Fuentes:
  FOMC  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  CPI   https://www.bls.gov/schedule/news_release/cpi.htm
Consultadas el 19/09/2026. Actualizar una vez al año.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Hasta donde llegan las tablas de abajo. Pasada esta fecha el modulo deja de
# prometer fechas exactas en vez de extrapolar.
VIGENCIA_TABLAS = date(2027, 12, 31)

# Segundo dia de cada reunion (el del comunicado y la rueda de prensa).
FOMC = [
    date(2026, 10, 28), date(2026, 12,  9),
    date(2027,  1, 27), date(2027,  3, 17), date(2027,  4, 28),
    date(2027,  6,  9), date(2027,  7, 28), date(2027,  9, 15),
    date(2027, 10, 27), date(2027, 12,  8),
]

# Fecha de publicacion -> mes de referencia del dato.
CPI = {
    date(2026, 10, 14): "septiembre 2026",
    date(2026, 11, 10): "octubre 2026",
    date(2026, 12, 10): "noviembre 2026",
}

_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_es(d: date) -> str:
    return f"{d.day} de {_MESES[d.month]}"


def _primer_viernes(anio: int, mes: int) -> date:
    d = date(anio, mes, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _proximo_nfp(hoy: date) -> date:
    """Nominas no agricolas: primer viernes de cada mes."""
    f = _primer_viernes(hoy.year, hoy.month)
    if f <= hoy:
        anio, mes = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
        f = _primer_viernes(anio, mes)
    return f


def _proximo_jueves(hoy: date) -> date:
    """Solicitudes iniciales de desempleo: todos los jueves."""
    return hoy + timedelta(days=((3 - hoy.weekday()) % 7) or 7)


def proximos_eventos(hoy: date = None, limite: int = 4) -> list:
    """
    Devuelve los proximos eventos macro ordenados por fecha.

    Cada evento: {nombre, fecha, fecha_texto, detalle, exacta}
    'exacta' en False significa que la fecha viene de una regla o esta fuera
    del calendario tabulado: se debe mostrar como aproximada.
    """
    hoy = hoy or date.today()
    eventos = []

    # ── FOMC ──────────────────────────────────────────────────────────────────
    siguientes = [d for d in FOMC if d > hoy]
    if siguientes:
        eventos.append({
            "nombre": "Decision de tasas de la Fed (FOMC)",
            "fecha": siguientes[0],
            "detalle": "Comunicado y rueda de prensa",
            "exacta": True,
        })
    elif hoy <= VIGENCIA_TABLAS:
        logger.warning("Calendario FOMC agotado antes de su vigencia declarada.")

    # ── CPI ───────────────────────────────────────────────────────────────────
    siguientes = sorted(d for d in CPI if d > hoy)
    if siguientes:
        eventos.append({
            "nombre": "Inflacion CPI",
            "fecha": siguientes[0],
            "detalle": f"Dato de {CPI[siguientes[0]]}",
            "exacta": True,
        })

    # ── NFP y solicitudes de desempleo (regla fija) ───────────────────────────
    f_nfp = _proximo_nfp(hoy)
    # Si cae en festivo grande, el BLS lo corre: no prometemos la fecha exacta.
    festivo = (f_nfp.month, f_nfp.day) in ((1, 1), (7, 3), (7, 4), (12, 25))
    eventos.append({
        "nombre": "Nominas no agricolas (NFP)",
        "fecha": f_nfp,
        "detalle": "Primer viernes del mes" + (" (puede correrse por festivo)" if festivo else ""),
        "exacta": not festivo,
    })
    eventos.append({
        "nombre": "Solicitudes iniciales de desempleo",
        "fecha": _proximo_jueves(hoy),
        "detalle": "Dato semanal",
        "exacta": True,
    })

    # ── Aviso si las tablas quedaron viejas ───────────────────────────────────
    if hoy > VIGENCIA_TABLAS:
        for e in eventos:
            e["exacta"] = False
        eventos.append({
            "nombre": "Calendario desactualizado",
            "fecha": hoy,
            "detalle": "Revisar federalreserve.gov y bls.gov: las tablas del bot vencieron",
            "exacta": False,
        })

    eventos.sort(key=lambda e: e["fecha"])
    for e in eventos:
        e["fecha_texto"] = fecha_es(e["fecha"])
        e["dias"] = (e["fecha"] - hoy).days
    return eventos[:limite]
