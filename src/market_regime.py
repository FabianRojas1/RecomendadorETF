"""
market_regime.py — Análisis macroeconómico: Bull/Bear Market Regime.

Obtiene indicadores en tiempo real via yfinance y los clasifica según el
framework de indicadores_portafolio_mapping.json para determinar si estamos
en BULL, NEUTRAL o BEAR market.

Indicadores de mercado (yfinance):
  - VIX                 → apetito de riesgo
  - 10Y Treasury Yield  → nivel (presión sobre growth)
  - Tendencia 10Y (3M)  → dirección de tasas
  - Curva 10Y vs T-Bill → señal de recesión
  - Dólar Index (DXY)   → headwind/tailwind para internacionales
  - SPY vs SMA200       → tendencia primaria del mercado

Indicadores macroeconómicos (FRED via pandas_datareader):
  - Tasa FED (FEDFUNDS)
  - Inflación CPI YoY (CPIAUCSL)
  - Empleo NFP (PAYEMS)
  - PIB EE.UU. (GDP)
  - UMich Consumer Sentiment (UMCSENT)
  - Solicitudes de desempleo iniciales (ICSA)
  - ISM Manufacturing PMI (NAPM)
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── Umbrales según el JSON de indicadores ─────────────────────────────────────
VIX_BULL  = 18     # por debajo = calma
VIX_BEAR  = 25     # por encima = estrés
YIELD_BULL_MAX   = 3.5   # 10Y < 3.5% → favorable growth
YIELD_BEAR_MIN   = 4.5   # 10Y > 4.5% → presión sobre tech
YIELD_TREND_BPTS = 0.10  # cambio de 10+ bps en 3M = señal
DXY_TREND_PCT    = 0.02  # movimiento > 2% en 3M = señal


def analyze_market_regime() -> dict:
    """
    Descarga indicadores macro y clasifica el régimen de mercado.

    Returns
    -------
    dict con campos:
        regime        : 'BULL' | 'NEUTRAL' | 'BEAR'
        bull_pct      : float 0-1 (% señales alcistas)
        bull_count    : int
        total_signals : int
        signals       : list[dict]  {name, value, signal, bull, desc}
        macro_data    : dict        indicadores FRED {fed_rate, nfp, cpi_yoy, gdp, umich, ...}
        strategy      : str         recomendación para portafolio agresivo
        fetch_date    : str
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance no disponible — saltando análisis de régimen")
        return _fallback()

    signals = []

    try:
        vix_df = yf.Ticker("^VIX").history(period="5d")
        tnx_df = yf.Ticker("^TNX").history(period="3mo")   # 10Y yield
        irx_df = yf.Ticker("^IRX").history(period="3mo")   # T-Bill corto
        dxy_df = yf.Ticker("DX-Y.NYB").history(period="3mo")
        spy_df = yf.Ticker("SPY").history(period="1y")

        if any(df.empty for df in [vix_df, tnx_df, irx_df, dxy_df, spy_df]):
            raise ValueError("Datos vacíos en uno o más tickers macro")

        vix_now = float(vix_df["Close"].iloc[-1])
        tnx_now = float(tnx_df["Close"].iloc[-1])
        tnx_3mo = float(tnx_df["Close"].iloc[0])
        irx_now = float(irx_df["Close"].iloc[-1])
        dxy_now = float(dxy_df["Close"].iloc[-1])
        dxy_3mo = float(dxy_df["Close"].iloc[0])
        spy_now = float(spy_df["Close"].iloc[-1])
        spy_sma = float(spy_df["Close"].rolling(min(200, len(spy_df))).mean().iloc[-1])

    except Exception as e:
        logger.error("Error descargando datos macro: %s", e)
        return _fallback(str(e))

    # ── Señal 1: VIX ──────────────────────────────────────────────────────────
    if vix_now < VIX_BULL:
        signals.append(_s(
            "VIX — Volatilidad/Miedo", f"{vix_now:.1f}",
            "ALCISTA", True,
            f"VIX {vix_now:.1f} < {VIX_BULL}: mercado en calma. "
            "Alto apetito de riesgo → favorable SOXX, QQQ, BTC, ETH."
        ))
    elif vix_now > VIX_BEAR:
        signals.append(_s(
            "VIX — Volatilidad/Miedo", f"{vix_now:.1f}",
            "BAJISTA", False,
            f"VIX {vix_now:.1f} > {VIX_BEAR}: estrés elevado. "
            "Mercado en modo miedo → reducir riesgo, considerar GLD."
        ))
    else:
        signals.append(_s(
            "VIX — Volatilidad/Miedo", f"{vix_now:.1f}",
            "NEUTRAL", None,
            f"VIX en zona neutra ({VIX_BULL}–{VIX_BEAR}). Vigilar tendencia."
        ))

    # ── Señal 2: Nivel del bono 10Y ───────────────────────────────────────────
    if tnx_now < YIELD_BULL_MAX:
        signals.append(_s(
            "Bono Tesoro 10Y (nivel)", f"{tnx_now:.2f}%",
            "ALCISTA", True,
            f"10Y < {YIELD_BULL_MAX}%: tasas bajas impulsan valuaciones. "
            "Flujos futuros de tech se descuentan menos → SOXX, QQQ."
        ))
    elif tnx_now > YIELD_BEAR_MIN:
        signals.append(_s(
            "Bono Tesoro 10Y (nivel)", f"{tnx_now:.2f}%",
            "BAJISTA", False,
            f"10Y > {YIELD_BEAR_MIN}%: tasas altas penalizan growth. "
            "Bonos compiten con acciones → reducir SOXX/BTC."
        ))
    else:
        signals.append(_s(
            "Bono Tesoro 10Y (nivel)", f"{tnx_now:.2f}%",
            "NEUTRAL", None,
            f"10Y en rango neutro ({YIELD_BULL_MAX}%–{YIELD_BEAR_MIN}%). Sin señal clara."
        ))

    # ── Señal 3: Tendencia del 10Y en 3 meses ─────────────────────────────────
    tnx_delta = tnx_now - tnx_3mo
    if tnx_delta < -YIELD_TREND_BPTS:
        signals.append(_s(
            "Tendencia Bono 10Y (3M)", f"{tnx_3mo:.2f}% → {tnx_now:.2f}% ({tnx_delta:+.2f}%)",
            "ALCISTA", True,
            "Yields bajando: expectativas de corte de tasas. "
            "Impulso para SOXX, QQQ y activos de crecimiento."
        ))
    elif tnx_delta > YIELD_TREND_BPTS:
        signals.append(_s(
            "Tendencia Bono 10Y (3M)", f"{tnx_3mo:.2f}% → {tnx_now:.2f}% ({tnx_delta:+.2f}%)",
            "BAJISTA", False,
            "Yields subiendo: presión sostenida sobre tech/crypto. "
            "Reducir exposición a growth si tendencia continúa."
        ))
    else:
        signals.append(_s(
            "Tendencia Bono 10Y (3M)", f"{tnx_3mo:.2f}% → {tnx_now:.2f}% ({tnx_delta:+.2f}%)",
            "NEUTRAL", None,
            "Yields estables en los últimos 3 meses. Sin cambio de régimen."
        ))

    # ── Señal 4: Curva de rendimientos (10Y vs T-Bill corto) ──────────────────
    spread = tnx_now - irx_now
    if spread > 0:
        signals.append(_s(
            "Curva Rendimientos (10Y - T-Bill)", f"{spread:+.2f}%",
            "ALCISTA", True,
            "Curva normal (+): mercado espera crecimiento económico. "
            "Contexto favorable para activos de riesgo."
        ))
    else:
        signals.append(_s(
            "Curva Rendimientos (10Y - T-Bill)", f"{spread:+.2f}%",
            "BAJISTA", False,
            "Curva INVERTIDA: señal histórica de recesión. "
            "Precaución máxima — reducir exposición a growth."
        ))

    # ── Señal 5: Dólar Index (DXY) ────────────────────────────────────────────
    dxy_chg = (dxy_now - dxy_3mo) / dxy_3mo
    if dxy_chg > DXY_TREND_PCT:
        signals.append(_s(
            "Dólar Index DXY (tendencia 3M)", f"{dxy_3mo:.1f} → {dxy_now:.1f} ({dxy_chg*100:+.1f}%)",
            "BAJISTA", False,
            f"Dólar fuerte ({dxy_chg*100:+.1f}%): headwind para VWO, IEFA y materias primas. "
            "GLD bajo presión. Crypto puede beneficiarse como alternativa."
        ))
    elif dxy_chg < -DXY_TREND_PCT:
        signals.append(_s(
            "Dólar Index DXY (tendencia 3M)", f"{dxy_3mo:.1f} → {dxy_now:.1f} ({dxy_chg*100:+.1f}%)",
            "ALCISTA", True,
            f"Dólar débil ({dxy_chg*100:+.1f}%): tailwind para VWO, GLD y mercados emergentes. "
            "Favorable para portafolio internacional."
        ))
    else:
        signals.append(_s(
            "Dólar Index DXY (tendencia 3M)", f"{dxy_now:.1f} (estable)",
            "NEUTRAL", None,
            "DXY sin tendencia clara. Sin impacto significativo en portafolio."
        ))

    # ── Señal 6: SPY vs Media Móvil 200 ───────────────────────────────────────
    spy_pct = (spy_now / spy_sma - 1) * 100
    spy_bull = spy_now > spy_sma
    signals.append(_s(
        "S&P 500 vs SMA 200", f"${spy_now:.0f} ({spy_pct:+.1f}% vs SMA200)",
        "ALCISTA" if spy_bull else "BAJISTA",
        spy_bull,
        (
            f"SPY {spy_pct:+.1f}% sobre SMA200: tendencia primaria alcista. "
            "Mercado saludable — mantener/aumentar exposición."
        ) if spy_bull else (
            f"SPY {spy_pct:+.1f}% bajo SMA200: tendencia primaria bajista. "
            "Mercado en modo corrección — revisar posiciones grandes."
        )
    ))

    # ── Indicadores macroeconómicos adicionales (FRED) ────────────────────────
    macro_data = _fetch_fred_macro()

    return _classify(signals, macro_data)


# ── FRED Macro indicators ─────────────────────────────────────────────────────

def _fetch_fred_macro() -> dict:
    """
    Descarga indicadores macroeconómicos de FRED via pandas_datareader.
    Requiere: pip install pandas-datareader

    Returns dict con claves: fed_rate, cpi_yoy, nfp, gdp, umich, initial_claims, ism_pmi
    Cada valor es un dict: {name, value, prev, dir, signal, note}
    En caso de error retorna {} (sin datos FRED).
    """
    try:
        import pandas_datareader.data as web
    except ImportError:
        logger.warning("pandas_datareader no instalado — sin indicadores FRED. "
                       "Instalar con: pip install pandas-datareader")
        return {}

    start = datetime.now() - timedelta(days=450)   # 15 meses para cálculos YoY
    out   = {}

    def _fred(series_id):
        """Descarga segura de una serie FRED. Retorna DataFrame o None."""
        try:
            df = web.DataReader(series_id, "fred", start=start)
            return df if not df.empty else None
        except Exception as e:
            logger.debug("FRED %s: %s", series_id, e)
            return None

    def _nd(name, note="Sin datos FRED"):
        """Indicador vacío cuando no hay datos disponibles."""
        return {"name": name, "value": "N/D", "prev": "—",
                "dir": "—", "signal": "N/D", "note": note}

    # ── Tasa FED (FEDFUNDS) ───────────────────────────────────────────────────
    df = _fred("FEDFUNDS")
    if df is not None and len(df) >= 2:
        v = float(df.iloc[-1, 0])
        p = float(df.iloc[-2, 0])
        d = "↑" if v > p + 0.01 else ("↓" if v < p - 0.01 else "↔")
        s = "BAJISTA" if v > p + 0.01 else ("ALCISTA" if v < p - 0.01 else "NEUTRAL")
        out["fed_rate"] = {
            "name": "Tasa FED",
            "value": f"{v:.2f}%",
            "prev":  f"{p:.2f}% (mes ant.)",
            "dir": d, "signal": s,
            "note": "Pausa activa — vigilar decisiones FOMC",
        }
    else:
        out["fed_rate"] = _nd("Tasa FED")

    # ── Inflación CPI YoY (CPIAUCSL) ─────────────────────────────────────────
    df = _fred("CPIAUCSL")
    if df is not None and len(df) >= 14:
        v0   = float(df.iloc[-1,  0])   # mes actual
        v1   = float(df.iloc[-2,  0])   # mes anterior
        v13  = float(df.iloc[-13, 0])   # hace 12 meses
        v14  = float(df.iloc[-14, 0])   # hace 13 meses
        yoy     = (v0 / v13 - 1) * 100
        yoy_prv = (v1 / v14 - 1) * 100
        d = "↑" if yoy > yoy_prv + 0.05 else ("↓" if yoy < yoy_prv - 0.05 else "↔")
        s = "BAJISTA" if yoy > 3.5 else ("ALCISTA" if yoy < 2.5 else "NEUTRAL")
        out["cpi_yoy"] = {
            "name":  "Inflación CPI",
            "value": f"{yoy:.1f}% YoY",
            "prev":  f"~{yoy_prv:.1f}% (mes ant.)",
            "dir": d, "signal": s,
            "note": f"Meta FED: 2%  |  {'Sobre umbral 3.5%' if yoy > 3.5 else 'Convergiendo al objetivo'}",
        }
    else:
        out["cpi_yoy"] = _nd("Inflación CPI")

    # ── NFP — Empleo No Agrícola (PAYEMS) ─────────────────────────────────────
    # PAYEMS está en miles de trabajadores; el diff mensual = variación NFP
    df = _fred("PAYEMS")
    if df is not None and len(df) >= 3:
        changes  = df.diff().dropna()
        nfp_now  = float(changes.iloc[-1, 0])   # miles de empleos añadidos
        nfp_prev = float(changes.iloc[-2, 0])
        d = "↑" if nfp_now > nfp_prev + 10 else ("↓" if nfp_now < nfp_prev - 10 else "↔")
        s = "BAJISTA" if nfp_now < 100 else ("ALCISTA" if nfp_now > 150 else "NEUTRAL")
        fmt = lambda x: f"+{x:.0f}K" if x >= 0 else f"{x:.0f}K"
        out["nfp"] = {
            "name":  "NFP Empleo",
            "value": fmt(nfp_now),
            "prev":  f"{fmt(nfp_prev)} (mes ant.)",
            "dir": d, "signal": s,
            "note": "> 150K alcista  |  < 100K bajista (Fed puede cortar)",
        }
    else:
        out["nfp"] = _nd("NFP Empleo")

    # ── PIB EE.UU. (GDP) ──────────────────────────────────────────────────────
    # GDP en miles de millones $. Tasa anualizada = ((v_now/v_prev)^4 - 1) * 100
    df = _fred("GDP")
    if df is not None and len(df) >= 3:
        v0 = float(df.iloc[-1, 0])
        v1 = float(df.iloc[-2, 0])
        v2 = float(df.iloc[-3, 0])
        gr_now  = ((v0 / v1) ** 4 - 1) * 100
        gr_prev = ((v1 / v2) ** 4 - 1) * 100
        d = "↑" if gr_now > gr_prev + 0.15 else ("↓" if gr_now < gr_prev - 0.15 else "↔")
        s = "ALCISTA" if gr_now > 2.5 else ("BAJISTA" if gr_now < 1.5 else "NEUTRAL")
        out["gdp"] = {
            "name":  "PIB EE.UU.",
            "value": f"{gr_now:+.1f}% anualizado",
            "prev":  f"{gr_prev:+.1f}% (trim. ant.)",
            "dir": d, "signal": s,
            "note": "> 2.5% alcista  |  < 1.5% zona de riesgo",
        }
    else:
        out["gdp"] = _nd("PIB EE.UU.")

    # ── UMich Consumer Sentiment (UMCSENT) ────────────────────────────────────
    df = _fred("UMCSENT")
    if df is not None and len(df) >= 2:
        v = float(df.iloc[-1, 0])
        p = float(df.iloc[-2, 0])
        d = "↑" if v > p + 0.5 else ("↓" if v < p - 0.5 else "↔")
        s = "BAJISTA" if v < 55 else ("ALCISTA" if v > 80 else "NEUTRAL")
        out["umich"] = {
            "name":  "UMich Sentiment",
            "value": f"{v:.1f}",
            "prev":  f"{p:.1f} (mes ant.)",
            "dir": d, "signal": s,
            "note": "< 55 consumidor pesimista  |  > 80 optimista",
        }
    else:
        out["umich"] = _nd("UMich Sentiment")

    # ── Solicitudes de Desempleo Iniciales (ICSA) ─────────────────────────────
    # ICSA en número de personas (no en miles); dividir para mostrar en K
    df = _fred("ICSA")
    if df is not None and len(df) >= 2:
        v = float(df.iloc[-1, 0])
        p = float(df.iloc[-2, 0])
        d = "↑" if v > p * 1.01 else ("↓" if v < p * 0.99 else "↔")
        s = "BAJISTA" if v > 260_000 else ("ALCISTA" if v < 210_000 else "NEUTRAL")
        out["initial_claims"] = {
            "name":  "Solicitudes Desempleo",
            "value": f"{v/1000:.0f}K",
            "prev":  f"{p/1000:.0f}K (sem. ant.)",
            "dir": d, "signal": s,
            "note": "> 260K señal de debilitamiento laboral",
        }
    else:
        out["initial_claims"] = _nd("Solicitudes Desempleo")

    # ── ISM Manufacturing PMI (NAPM) ──────────────────────────────────────────
    df = _fred("NAPM")
    if df is not None and len(df) >= 2:
        v = float(df.iloc[-1, 0])
        p = float(df.iloc[-2, 0])
        d = "↑" if v > p + 0.1 else ("↓" if v < p - 0.1 else "↔")
        s = "ALCISTA" if v > 50 else "BAJISTA"
        out["ism_pmi"] = {
            "name":  "ISM Manufacturing PMI",
            "value": f"{v:.1f}",
            "prev":  f"{p:.1f} (mes ant.)",
            "dir": d, "signal": s,
            "note": "> 50 expansión manufacturera",
        }
    else:
        # ISM a veces no está disponible en FRED (datos privados)
        out["ism_pmi"] = _nd("ISM Manufacturing PMI",
                             note="Datos privados — ver ISM.report/manufacturing")

    logger.info("Indicadores FRED obtenidos: %d/%d",
                sum(1 for v in out.values() if v.get("value") != "N/D"), len(out))
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _s(name, value, signal, bull, desc):
    """Construye un dict de señal."""
    return {"name": name, "value": value, "signal": signal, "bull": bull, "desc": desc}


def _classify(signals: list, macro_data: dict = None) -> dict:
    """Clasifica el régimen y genera estrategia."""
    bull_n = len([s for s in signals if s["bull"] is True])
    total  = len([s for s in signals if s["bull"] is not None])
    pct    = bull_n / total if total else 0.5

    if pct >= 0.65:
        regime = "BULL"
        strategy = (
            "GROWTH MODE activo. Condiciones macro favorecen crecimiento. "
            "Mantener o aumentar SOXX, QQQ, BTC, ETH. "
            "Reducir defensivos si sobreponderados (XLV > 15%). "
            "Vigilar próximos datos: FOMC, CPI, NFP."
        )
    elif pct <= 0.35:
        regime = "BEAR"
        strategy = (
            "DEFENSIVE MODE recomendado. Señales de cautela activas. "
            "Reducir SOXX y BTC/ETH (primeros en sufrir en bear). "
            "Aumentar GLD como cobertura. Reforzar XLV, IFRA. "
            "No escalar posiciones de riesgo hasta mejora de condiciones."
        )
    else:
        regime = "NEUTRAL"
        strategy = (
            "ZONA DE TRANSICIÓN. Señales mixtas — sin claridad de dirección. "
            "Mantener posiciones actuales sin escalar extremos. "
            "Esperar confirmación en próximos catalizadores: "
            "decisión FOMC, CPI, reporte de empleo (NFP)."
        )

    return {
        "regime":        regime,
        "bull_pct":      pct,
        "bull_count":    bull_n,
        "total_signals": total,
        "signals":       signals,
        "macro_data":    macro_data or {},
        "strategy":      strategy,
        "fetch_date":    datetime.now().strftime("%d/%m/%Y %H:%M"),
    }


def _fallback(error: str = "") -> dict:
    return {
        "regime":        "NEUTRAL",
        "bull_pct":      0.5,
        "bull_count":    0,
        "total_signals": 0,
        "signals":       [],
        "macro_data":    {},
        "strategy":      "No se pudieron obtener datos macro. Revisar conectividad.",
        "fetch_date":    datetime.now().strftime("%d/%m/%Y %H:%M"),
        "error":         error,
    }
