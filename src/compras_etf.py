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
MAX_CERCA = 10          # cuántas "cerca del gatillo" se muestran en el PDF


def _cercania_gatillo(v: dict, mp: dict) -> dict:
    """
    Qué tan cerca está del gatillo MP una acción que ya tiene contexto y ubicación.
    Solo ordena la lista del PDF; no cambia ninguna señal. Menor 'orden' = más cerca.
      1. cuántos ítems del gatillo faltan (0-2)
      2. SQZ semanal en rojo oscuro (bajista perdiendo fuerza: antesala del giro)
      3. distancia del cierre a la EMA10 semanal, en ATR semanales
    """
    faltan = [i for i in (mp.get("gatillo") or []) if i.get("cumple") is not True]
    close, e10, atr = v.get("sem_close"), v.get("sem_ema10"), v.get("sem_atr")
    dist = max(0.0, (e10 - close) / atr) if close and e10 and atr else 9.9
    rojo_oscuro = v.get("sem_sqz_color") == "rojo_oscuro"
    textos = []
    for i in faltan:
        if i["item"].startswith("SQZ") and e10:
            textos.append(f"cierre sobre EMA10 sem. ${e10:,.2f} (a {dist:.1f} ATR)")
        elif i["item"].startswith("OBV"):
            textos.append("OBV sobre su EMA20")
        else:
            textos.append(i["item"])
    return {"orden": (len(faltan), 0 if rojo_oscuro else 1, dist), "faltan": textos,
            "distancia_atr": round(dist, 2), "sqz_rojo_oscuro": rojo_oscuro}


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
    n_datos = n_sin_datos = n_lp = n_compra_total = 0
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
                n_compra_total += 1
                # En el PDF solo van: LP con gatillo MP (COMPRAR) y las más cercanas al gatillo
                # (COMPRAR (LP) con MP al 60%: contexto y ubicación OK, falta solo el gatillo).
                if comb["accion"] == "COMPRAR":
                    grupo, cercania = "gatillo", None
                elif comb["accion"] == "COMPRAR (LP)" and mp.get("confianza_pct") == 60:
                    grupo, cercania = "cerca", _cercania_gatillo(v, mp)
                else:
                    continue
                f = universo[t]
                compras.append({
                    "grupo": grupo, "cercania": cercania,
                    "categoria_universo": f.get("categoria", ""), "etiqueta": f.get("etiqueta", ""),
                    "calidad": f.get("calidad"), "riesgo": f.get("riesgo", ""),
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

    gatillo = sorted((r for r in compras if r["grupo"] == "gatillo"),
                     key=lambda r: (-r["lp_conf"], -(r["calidad"] or 0), r["ticker"]))
    cerca = sorted((r for r in compras if r["grupo"] == "cerca"), key=lambda r: r["cercania"]["orden"])
    n_cerca_total = len(cerca)
    compras = gatillo + cerca[:MAX_CERCA]
    meta = {"fecha": hoy.isoformat(), "fecha_universo": getattr(mod, "FECHA_UNIVERSO", "N/D"),
            "etfs": [c["ETF"] for c in getattr(mod, "COBERTURA", [])],
            "cobertura": getattr(mod, "COBERTURA", []),
            "universo": len(universo), "excluidas_portafolio": len(universo) - len(tickers),
            "evaluadas": n_datos, "sin_datos": n_sin_datos, "pasan_lp": n_lp,
            "compras_total": n_compra_total, "con_gatillo": len(gatillo),
            "cerca_total": n_cerca_total, "cerca_mostradas": min(n_cerca_total, MAX_CERCA),
            "compras": len(compras)}
    logger.info("Compras ETF: %d evaluadas · %d pasan LP · %d con gatillo · %d cerca del gatillo",
                n_datos, n_lp, len(gatillo), n_cerca_total)
    return {"compras": compras, "meta": meta}
