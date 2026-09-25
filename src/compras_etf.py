"""
compras_etf.py - Compras en acciones individuales de los ETFs de referencia.

Escanea las acciones de SP500, REMX, SOXX, QQQ, QTUM, BATT, XLV, MCHI, VXUS,
IWVL e ICLN que cotizan en bolsa de EE.UU. (lista fija en src/universo_etfs.py)
con EXACTAMENTE la misma logica de compra del reporte semanal:

    IndicatorCalculator  ->  signals.evaluar_lp / evaluar_mp  ->  signals.combinar
    -> signals.ACCION_A_CATEGORIA  ->  "COMPRA" en la categoria

Por etapas, para que el escaneo quepa en la corrida semanal:
  1. Precios por lotes (una peticion por lote, no una por accion).
  2. Etapa LP: solo el marco mensual. Se descarta lo que el LP no deja comprar
     con ningun estado de MP (signals.lp_puede_comprar le pregunta a combinar()).
  3. Etapa MP: marco semanal SOLO para las sobrevivientes, y combinar().

No consulta paginas de emisores ni fichas de empresas: eso lo hace una vez
tools/actualizar_universo_etfs.py, que escribe src/universo_etfs.py.
"""
import importlib
import logging
import os
from datetime import date

import pandas as pd

from src import estado_senales
from src import signals as lp_mp
from src.indicators import IndicatorCalculator

logger = logging.getLogger(__name__)

TAM_LOTE = 100          # acciones por peticion a Yahoo
MIN_FILAS = 60          # mismo minimo que main.py para el portafolio
ORDEN_ACCION = {"COMPRAR": 0, "COMPRAR (LP)": 1, "ENTRADA TACTICA": 2}


def cargar_universo():
    """Devuelve el modulo src/universo_etfs.py o None si aun no se ha generado."""
    try:
        return importlib.import_module("src.universo_etfs")
    except ModuleNotFoundError:
        return None


def ruta_estado(config=None) -> str:
    return os.path.join(os.path.dirname(estado_senales.ruta_por_defecto(config)), "estado_senales_etf.json")


def _descargar_lote(tickers: list, periodo: str) -> dict:
    """Mismo origen y ajuste que DataLoader.download_history, pero en un solo llamado."""
    import yfinance as yf
    try:
        raw = yf.download(tickers, period=periodo, auto_adjust=True, progress=False,
                          group_by="ticker", threads=True)
    except Exception as e:  # noqa: BLE001 - un lote caido no tumba el reporte
        logger.warning("Lote de %d acciones sin datos: %s", len(tickers), e)
        return {}
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        # El lote alinea fechas de todas las acciones: se quitan las filas vacias
        # para dejar la misma serie que bajaria la accion sola.
        df = df.dropna(subset=["Close"])
        if not df.empty:
            df.index.name = "Date"
            out[t] = df
    return out


def analizar(excluir=(), periodo: str = "max", config=None, hoy: date = None) -> dict:
    """
    Devuelve {"compras": [...], "meta": {...}} o {"compras": [], "meta": {"error": ...}}.
    excluir: tickers que ya estan en el portafolio (ya salen en la seccion COMPRAS).
    """
    hoy = hoy or date.today()
    mod = cargar_universo()
    if mod is None:
        msg = ("Falta src/universo_etfs.py: corre el workflow 'Actualizar universo ETF' "
               "(o tools/actualizar_universo_etfs.py) una vez.")
        logger.warning(msg)
        return {"compras": [], "meta": {"error": msg}}

    universo = mod.UNIVERSO
    excluir = {str(t).upper() for t in excluir}
    tickers = [t for t in universo if t.upper() not in excluir]
    ruta = ruta_estado(config)
    estado = estado_senales.cargar(ruta)
    sobrevivientes_lp = set()
    n_datos = n_sin_datos = n_lp = 0
    compras = []

    for i in range(0, len(tickers), TAM_LOTE):
        lote = tickers[i:i + TAM_LOTE]
        precios = _descargar_lote(lote, periodo)
        for t in lote:
            df = precios.get(t)
            if df is None or len(df) < MIN_FILAS:
                n_sin_datos += 1
                continue
            try:
                calc = IndicatorCalculator(df)
                # ── Etapa 1: LP (marco mensual) ─────────────────────────────
                v = calc.valores_lp()
                lp = lp_mp.evaluar_lp(v)
                n_datos += 1
                if not lp_mp.lp_puede_comprar(lp):
                    continue
                n_lp += 1
                sobrevivientes_lp.add(t)
                # ── Etapa 2: MP (marco semanal) solo para sobrevivientes ─────
                v.update(calc.valores_mp())
                mp = lp_mp.evaluar_mp(v)
                vig = estado_senales.actualizar(estado, t, f"{lp['estado']}|{mp['estado']}", hoy)
                comb = lp_mp.combinar(lp, mp, semanas_en_estado=vig["semanas"], tiene_posicion=False)
                categoria = lp_mp.ACCION_A_CATEGORIA.get(comb.get("accion", "SIN DATOS"), "MANTENER")
                if "COMPRA" not in categoria:
                    continue
                f = universo[t]
                compras.append({
                    "ticker": t, "empresa": f.get("empresa", t), "actividad": f.get("actividad", "N/D"),
                    "sector": f.get("sector", "N/D"), "pais": f.get("pais", "N/D"),
                    "tipo": " · ".join(p for p in (f.get("estilo"), f.get("tamano"), f.get("ciclo"))
                                       if p and p not in ("N/D", "Cap. N/D")) or "N/D",
                    "descripcion": f.get("descripcion", ""), "etfs": f.get("etfs", ""),
                    "accion": comb["accion"], "categoria": categoria, "texto": comb.get("texto", ""),
                    "avisos": comb.get("avisos", []),
                    "lp_estado": lp["estado"], "lp_conf": lp.get("confianza_pct", 0),
                    "mp_estado": mp["estado"], "mp_conf": mp.get("confianza_pct", 0),
                    "precio": float(df["Close"].iloc[-1]),
                    "invalidacion": lp.get("invalidacion"), "stop_mp": mp.get("stop_mp"),
                    "vigencia": vig,
                })
            except Exception as e:  # noqa: BLE001
                logger.debug("%s: omitido (%s)", t, e)
                n_sin_datos += 1
        logger.info("Compras ETF: %d/%d acciones procesadas", min(i + TAM_LOTE, len(tickers)), len(tickers))

    # Memoria de señales: solo las que siguen pasando el LP (si una sale y vuelve,
    # su contador arranca de cero, como en el portafolio cuando cambia la señal).
    estado_senales.guardar({t: d for t, d in estado.items() if t in sobrevivientes_lp}, ruta, hoy)

    compras.sort(key=lambda r: (ORDEN_ACCION.get(r["accion"], 9), -r["mp_conf"], -r["lp_conf"], r["ticker"]))
    meta = {"fecha": hoy.isoformat(), "fecha_universo": getattr(mod, "FECHA_UNIVERSO", "N/D"),
            "etfs": [c["ETF"] for c in getattr(mod, "COBERTURA", [])],
            "cobertura": getattr(mod, "COBERTURA", []),
            "universo": len(universo), "excluidas_portafolio": len(universo) - len(tickers),
            "evaluadas": n_datos, "sin_datos": n_sin_datos, "pasan_lp": n_lp, "compras": len(compras)}
    logger.info("Compras ETF: %d evaluadas · %d pasan LP · %d con compra", n_datos, n_lp, len(compras))
    return {"compras": compras, "meta": meta}
