"""
ordenes_hapi.py - Actualiza portfolio.csv con las órdenes ejecutadas de Hapi.

Las órdenes llegan por correo ("Order Executed"). Un Apps Script en la cuenta de
Google del usuario las copia a una hoja y las expone en una URL con token
(tools/apps_script/). Este modulo:

  1. Trae las órdenes de esa URL.
  2. Aplica solo las nuevas (ids en data/ordenes_hapi.json) y posteriores a
     FECHA_CORTE (lo anterior ya está reflejado en portfolio.csv).
  3. Compra existente: suma cantidad. Venta: resta; si queda en cero, el activo
     vuelve a la Watchlist con su categoria. Compra nueva: categoria de la
     Watchlist si estaba ahi; si no, la clasifica (ficha del universo de ETFs o
     Yahoo) y la marca "(auto)".
  4. Escribe data/ordenes_resumen.json para el reporte (una linea en Telegram y
     en la portada del PDF; ningun mensaje aparte).

Corre como paso propio del workflow, antes del analisis, para que el token solo
este disponible en ese paso:   python -m src.ordenes_hapi

Nunca rompe la corrida semanal: ante cualquier error, deja el CSV como estaba y
lo anota en el resumen.
"""
import csv
import importlib.util
import io
import json
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

FECHA_CORTE = "2026-10-17"   # foto del portafolio: las órdenes hasta este dia ya estan en el CSV
CERO = 1e-6                  # cantidad que se considera posicion cerrada

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_CSV = os.path.join(BASE_DIR, "portfolio.csv")
RUTA_PROCESADAS = os.path.join(BASE_DIR, "data", "ordenes_hapi.json")
RUTA_RESUMEN = os.path.join(BASE_DIR, "data", "ordenes_resumen.json")


# ── Lectura de la hoja ──────────────────────────────────────────────────────

def traer_ordenes(url: str, token: str, timeout: int = 90) -> list:
    import requests
    r = requests.get(url, params={"token": token}, timeout=timeout)
    r.raise_for_status()
    datos = r.json()
    if "error" in datos:
        raise RuntimeError(f"la hoja respondio: {datos['error']}")
    return datos.get("ordenes") or []


# ── Clasificacion de un activo nuevo ────────────────────────────────────────

# Ficha del universo (sector en español, ciclo de Morningstar)
_SECTOR_UNIVERSO = {"Materiales básicos": "Materias Primas", "Industrial": "Sectorial",
                    "Energía": "Sectorial", "Inmobiliario": "Sectorial"}
# Yahoo, acciones (sector en ingles)
_SECTOR_YAHOO = {"Healthcare": "Defensiva", "Consumer Defensive": "Defensiva", "Utilities": "Defensiva",
                 "Basic Materials": "Materias Primas", "Industrials": "Sectorial", "Energy": "Sectorial",
                 "Real Estate": "Sectorial"}
# Yahoo, ETFs (categoria de Morningstar): palabras clave en orden de prioridad
_CATEGORIA_ETF = [
    (("digital asset", "crypto", "bitcoin"), "Cripto"),
    (("emerging", "foreign", "china", "india", "japan", "europe", "latin", "pacific", "international"),
     "Global ex-EE.UU."),
    (("natural resources", "commodit", "precious metal", "gold", "metals"), "Materias Primas"),
    (("health", "consumer defensive", "utilities"), "Defensiva"),
    (("industrials", "energy", "real estate", "infrastructure"), "Sectorial"),
]


def _universo():
    try:
        spec = importlib.util.spec_from_file_location("universo_etfs", os.path.join(BASE_DIR, "src", "universo_etfs.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "UNIVERSO", {})
    except Exception:  # noqa: BLE001
        return {}


def clasificar(ticker: str, universo: dict = None) -> dict:
    """{"categoria", "subtipo", "nombre", "fuente"} para un ticker que no estaba en el CSV."""
    f = (universo if universo is not None else _universo()).get(ticker)
    if f:
        if f.get("pais") and f["pais"] != "EE.UU.":
            cat = "Global ex-EE.UU."
        elif f.get("ciclo") == "Defensiva":
            cat = "Defensiva"
        else:
            cat = _SECTOR_UNIVERSO.get(f.get("sector"), "Crecimiento")
        return {"categoria": cat, "subtipo": f.get("sector") or "", "nombre": f.get("empresa") or ticker,
                "fuente": "universo"}
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception:  # noqa: BLE001
        info = {}
    nombre = info.get("shortName") or info.get("longName") or ticker
    if info.get("quoteType") == "ETF":
        texto = (info.get("category") or "").lower()
        cat = next((c for claves, c in _CATEGORIA_ETF if any(k in texto for k in claves)), "Crecimiento")
        return {"categoria": cat, "subtipo": info.get("category") or "ETF", "nombre": nombre, "fuente": "yahoo"}
    if info:
        pais = info.get("country")
        cat = ("Global ex-EE.UU." if pais and pais != "United States"
               else _SECTOR_YAHOO.get(info.get("sector"), "Crecimiento"))
        return {"categoria": cat, "subtipo": info.get("sector") or "", "nombre": nombre, "fuente": "yahoo"}
    return {"categoria": "Crecimiento", "subtipo": "", "nombre": ticker, "fuente": "sin datos"}


# ── Aplicacion sobre el CSV ─────────────────────────────────────────────────

def _f(x):
    try:
        return float(str(x).replace(",", "")) if x not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _fmt(x: float) -> str:
    """Todos los decimales utiles, sin notacion cientifica ni ceros sobrantes."""
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def aplicar(ordenes: list, filas: list, procesadas: dict, clasificador=clasificar) -> tuple:
    """
    Aplica las órdenes nuevas sobre las filas del CSV (lista de dicts, se modifica).
    Devuelve (aplicadas, pendientes) para el resumen.
    """
    aplicadas, pendientes = [], []
    universo = None

    def descartar(oid, o, ticker, motivo):
        # No se podra aplicar nunca: se informa una sola vez y se marca como procesada
        pendientes.append({"id": oid, "ticker": ticker, "motivo": motivo})
        procesadas[oid] = {"fecha": str(o.get("fecha", ""))[:10], "ticker": ticker, "descartada": motivo}

    for o in sorted(ordenes, key=lambda x: str(x.get("fecha", ""))):
        oid = str(o.get("id", ""))
        if not oid or oid in procesadas:
            continue
        if str(o.get("fecha", ""))[:10] <= FECHA_CORTE:
            continue
        ticker = str(o.get("ticker") or "").strip().upper()
        if o.get("error") or not ticker:
            pendientes.append({"id": oid, "ticker": ticker or "?", "motivo": o.get("error") or "sin ticker"})
            continue
        if "complet" not in str(o.get("estado", "")).lower():
            descartar(oid, o, ticker, f"estado '{o.get('estado')}'")
            continue

        op = str(o.get("operacion", "")).strip().lower()
        cant, precio, costo = _f(o.get("cantidad")), _f(o.get("precio")), _f(o.get("costo"))
        if op not in ("buy", "sell") or cant <= 0:
            descartar(oid, o, ticker, "operacion o cantidad invalida")
            continue

        hapi = next((r for r in filas if r["ticker"] == ticker and r["broker"] == "Hapi"), None)
        vigilada = next((r for r in filas if r["ticker"] == ticker and r["broker"] == "Watchlist"), None)
        detalle = {"ticker": ticker, "operacion": "compra" if op == "buy" else "venta",
                   "cantidad": cant, "precio": precio, "nueva": False, "categoria": None, "auto": False}

        if op == "buy":
            valor = costo or cant * precio
            if hapi:
                hapi["quantity"] = _fmt(_f(hapi["quantity"]) + cant)
                hapi["current_value"] = _fmt(_f(hapi["current_value"]) + valor)
            else:
                detalle["nueva"] = True
                if vigilada:
                    fila = vigilada   # conserva nombre y categoria de la Watchlist
                else:
                    if universo is None:
                        universo = _universo()
                    c = clasificador(ticker, universo)
                    fila = {k: "" for k in filas[0].keys()}
                    fila.update(ticker=ticker, asset_name=c["nombre"], asset_type=c["categoria"],
                                asset_subtype=(c["subtipo"] + " (auto)").strip())
                    filas.append(fila)
                    detalle["auto"] = True
                fila.update(broker="Hapi", currency="USD", quantity=_fmt(cant), entry_price=_fmt(precio),
                            current_value=_fmt(valor), entry_date=str(o.get("fecha", ""))[:10])
                detalle["categoria"] = fila["asset_type"]
        else:
            if not hapi:
                descartar(oid, o, ticker, "venta de un activo que no esta en Hapi")
                continue
            queda = _f(hapi["quantity"]) - cant
            if queda <= CERO:
                hapi.update(broker="Watchlist", quantity="0.0", current_value="0.0",
                            entry_price="0.0", pct_of_total_portfolio="0%")
                detalle["cerrada"] = True
            else:
                hapi["quantity"] = _fmt(queda)
                hapi["current_value"] = _fmt(max(0.0, _f(hapi["current_value"]) - cant * precio))

        procesadas[oid] = {"fecha": str(o.get("fecha", ""))[:10], "ticker": ticker, "operacion": detalle["operacion"],
                           "cantidad": cant}
        aplicadas.append(detalle)
    return aplicadas, pendientes


def texto_resumen(resumen: dict) -> str:
    """Una linea para Telegram y la portada del PDF. Vacio si no hubo nada."""
    if not resumen:
        return ""
    partes = []
    for a in resumen.get("aplicadas") or []:
        signo = "+" if a["operacion"] == "compra" else "-"
        p = f"{signo}{_fmt(a['cantidad'])} {a['ticker']}"
        if a.get("nueva"):
            p += f" (nueva: {a['categoria']}{', auto' if a.get('auto') else ''})"
        if a.get("cerrada"):
            p += " (cerrada, a Watchlist)"
        partes.append(p)
    pend = resumen.get("pendientes") or []
    if pend:
        partes.append(f"{len(pend)} sin aplicar ({', '.join(x['ticker'] for x in pend)}): revisar hoja")
    if resumen.get("error"):
        partes.append("no se pudo leer la hoja de órdenes")
    return ("Órdenes Hapi: " + " · ".join(partes)) if partes else ""


def leer_resumen(hoy: date = None) -> dict:
    """Resumen de esta corrida (si es de hoy) para el reporte."""
    hoy = hoy or date.today()
    try:
        with open(RUTA_RESUMEN, encoding="utf-8") as fh:
            r = json.load(fh)
        return r if r.get("fecha") == hoy.isoformat() else {}
    except Exception:  # noqa: BLE001
        return {}


# ── Paso del workflow ───────────────────────────────────────────────────────

def _leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return defecto


def _escribir_json(ruta, obj):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    hoy = date.today().isoformat()
    url, token = os.getenv("HAPI_ORDENES_URL"), os.getenv("HAPI_ORDENES_TOKEN")
    if not url or not token:
        logger.info("Órdenes Hapi: sin HAPI_ORDENES_URL/TOKEN, se omite.")
        return 0
    resumen = {"fecha": hoy, "aplicadas": [], "pendientes": []}
    try:
        ordenes = traer_ordenes(url, token)
        with open(RUTA_CSV, encoding="utf-8", newline="") as fh:
            texto = fh.read()
        crlf = "\r\n" in texto
        lector = csv.DictReader(io.StringIO(texto))
        campos, filas = lector.fieldnames, list(lector)
        estado = _leer_json(RUTA_PROCESADAS, {"procesadas": {}})
        aplicadas, pendientes = aplicar(ordenes, filas, estado["procesadas"])
        resumen.update(aplicadas=aplicadas, pendientes=pendientes)
        if aplicadas:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=campos, lineterminator="\r\n" if crlf else "\n")
            w.writeheader()
            w.writerows(filas)
            with open(RUTA_CSV, "w", encoding="utf-8", newline="") as fh:
                fh.write(buf.getvalue())
        if aplicadas or any(p["id"] in estado["procesadas"] for p in pendientes):
            # despues del CSV: si escribir el CSV falla, las órdenes se reintentan
            estado["actualizado"] = datetime.now().isoformat(timespec="seconds")
            _escribir_json(RUTA_PROCESADAS, estado)
        logger.info("Órdenes Hapi: %d aplicadas, %d pendientes", len(aplicadas), len(pendientes))
    except Exception as e:  # noqa: BLE001
        logger.error("Órdenes Hapi: %s (el portafolio queda como estaba)", e)
        resumen["error"] = str(e)[:200]
    _escribir_json(RUTA_RESUMEN, resumen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
