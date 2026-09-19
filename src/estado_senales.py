"""
estado_senales.py - Memoria minima de cuanto lleva activa cada señal.

Guarda SOLO la fecha en que aparecio por primera vez la combinacion de estados
LP|MP de cada ticker. No es un registro de compras, precios ni tramos: sirve
para responder "esta señal lleva X semanas activa" y para disparar el aviso de
comprar el tramo LP cuando el gatillo de MP no llega en 4-6 semanas.

Por que un JSON y no la base de datos:
en GitHub Actions el contenedor se descarta al terminar la corrida, asi que
todo lo que se escriba en data/inversiones.db durante la ejecucion se pierde.
Este archivo es texto plano, diffeable, y el workflow le hace commit despues de
cada analisis para que la memoria sobreviva de una semana a la siguiente.
"""
import json
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

RETENCION_DIAS = 400   # se descartan tickers que no aparecen hace mas de un año


def ruta_por_defecto(config=None) -> str:
    base = getattr(config, "BASE_DIR", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "estado_senales.json")


def _a_fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def cargar(ruta: str) -> dict:
    """Lee el estado guardado. Devuelve {} si no existe o esta corrupto."""
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except Exception as e:
        logger.warning("No se pudo leer %s (%s): se parte de cero.", ruta, e)
        return {}


def actualizar(estado: dict, ticker: str, clave: str, hoy: date = None) -> dict:
    """
    Registra la señal vigente de un ticker y devuelve cuanto lleva activa.

    clave: identificador de la señal, tipicamente "<estado LP>|<estado MP>".
           Si cambia respecto a la corrida anterior, el contador se reinicia.

    Devuelve {"semanas": int, "desde": "YYYY-MM-DD", "cambio": bool}.
    """
    hoy = hoy or date.today()
    previo = estado.get(ticker) or {}
    cambio = previo.get("senal") != clave

    if cambio:
        desde = hoy
    else:
        desde = _a_fecha(previo.get("desde")) or hoy

    estado[ticker] = {
        "senal": clave,
        "desde": desde.isoformat(),
        "ultima_vez": hoy.isoformat(),
    }
    return {
        "semanas": max(0, (hoy - desde).days // 7),
        "desde": desde.isoformat(),
        "cambio": cambio,
    }


def guardar(estado: dict, ruta: str, hoy: date = None) -> bool:
    """Escribe el estado, descartando tickers que no aparecen hace mucho."""
    hoy = hoy or date.today()
    vigente = {}
    for ticker, datos in (estado or {}).items():
        visto = _a_fecha((datos or {}).get("ultima_vez"))
        if visto is None or (hoy - visto).days <= RETENCION_DIAS:
            vigente[ticker] = datos
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(vigente, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        return True
    except Exception as e:
        logger.error("No se pudo guardar %s: %s", ruta, e)
        return False
