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

    # -- Tasa FED (FEDFUNDS + SOFR como watchdog) -----------
    # Estrategia: Signal basada en RANGO DE FEDFUNDS (cambios mes anterior vs actual)
    #            SOFR es informativo (verifica si FEDFUNDS está actualizado)
    fed_rate_fresco = None
    
    try:
        # FEDFUNDS: obtener últimos 3 meses para ver tendencia
        df_fed = _fred("FEDFUNDS")
        if df_fed is not None and len(df_fed) >= 3:
            fed_now = float(df_fed.iloc[-1, 0])   # Mes actual
            fed_1m = float(df_fed.iloc[-2, 0])    # Mes anterior
            fed_2m = float(df_fed.iloc[-3, 0])    # Hace 2 meses
            
            # Determinar cambio de FEDFUNDS (política monetaria)
            if fed_now > fed_1m + 0.10:
                cambio = "↑ SUBIO"
                signal_fed = "BAJISTA"
            elif fed_now < fed_1m - 0.10:
                cambio = "↓ BAJO"
                signal_fed = "ALCISTA"
            else:
                cambio = "↔ Sin cambio"
                signal_fed = "NEUTRAL"
            
            # Tendencia últimos 3 meses
            if fed_2m > fed_now:
                tendencia = "↓ bajista"
            elif fed_2m < fed_now:
                tendencia = "↑ alcista"
            else:
                tendencia = "→ estable"
            
            # Obtener SOFR para verificación (solo informativo)
            sofr_nota = ""
            try:
                df_sofr = web.DataReader("SOFR", "fred", start=start)
                if df_sofr is not None and len(df_sofr) >= 1:
                    sofr_actual = float(df_sofr.iloc[-1, 0])
                    fed_lower = fed_now - 0.125
                    fed_upper = fed_now + 0.125
                    if sofr_actual > fed_upper:
                        sofr_nota = f"⚠️ REVISAR: SOFR {sofr_actual:.2f}% ARRIBA del rango {fed_lower:.2f}-{fed_upper:.2f}%"
                    elif sofr_actual < fed_lower:
                        sofr_nota = f"⚠️ REVISAR: SOFR {sofr_actual:.2f}% ABAJO del rango {fed_lower:.2f}-{fed_upper:.2f}%"
                    else:
                        sofr_nota = f"✓ SOFR {sofr_actual:.2f}% dentro del rango {fed_lower:.2f}-{fed_upper:.2f}%"
            except:
                sofr_nota = ""
            
            fed_rate_fresco = {
                "name": "Tasa FED (FEDFUNDS)",
                "value": f"{fed_now:.2f}%",
                "prev": f"{fed_1m:.2f}% (mes ant.)",
                "dir": "↑" if signal_fed == "BAJISTA" else ("↓" if signal_fed == "ALCISTA" else "↔"),
                "signal": signal_fed,
                "note": f"{cambio} | Tendencia 3m: {tendencia}{sofr_nota}",
            }
    except:
        pass
    
    out["fed_rate"] = fed_rate_fresco if fed_rate_fresco else _nd("Tasa FED")

    # -- Inflacion CPI YoY (CPIAUCSL) --------
    # Signal basada en TENDENCIA (aceleracion/desaceleracion), no nivel absoluto
    # Justificacion: llevan anos por encima de la meta, lo que importa es si mejora o empeora
    df = _fred("CPIAUCSL")
    if df is not None and len(df) >= 14:
        v0   = float(df.iloc[-1,  0])   # mes actual
        v1   = float(df.iloc[-2,  0])   # mes anterior
        v13  = float(df.iloc[-13, 0])   # hace 12 meses
        v14  = float(df.iloc[-14, 0])   # hace 13 meses
        
        # Calcular YoY para mes actual y anterior
        yoy     = (v0 / v13 - 1) * 100
        yoy_prv = (v1 / v14 - 1) * 100
        
        # METRICA PRINCIPAL: Tendencia (aceleracion/desaceleracion)
        yoy_change = yoy - yoy_prv
        
        if yoy_change > 0.3:
            s = "BAJISTA"  # inflacion acelerando (empeorando)
            trend_msg = "↑ acelerando"
        elif yoy_change < -0.3:
            s = "ALCISTA"   # inflacion desacelerando (mejorando)
            trend_msg = "↓ desacelerando"
        else:
            s = "NEUTRAL"  # tendencia estable
            trend_msg = "→ estable"
        
        # Direccion visual basada en cambio
        d = "↑" if yoy_change > 0.1 else ("↓" if yoy_change < -0.1 else "↔")
        
        out["cpi_yoy"] = {
            "name":  "Inflacion CPI",
            "value": f"{yoy:.1f}% YoY",
            "prev":  f"~{yoy_prv:.1f}% (mes ant.)",
            "dir": d, "signal": s,
            "note": f"Meta FED 2%  |  Tendencia: {trend_msg} ({yoy_change:+.2f}%)",
        }
    else:
        out["cpi_yoy"] = _nd("Inflacion CPI")
    # ── NFP — Empleo No Agrícola (PAYEMS) ─────────────────────────────────────
    # PAYEMS está en miles de trabajadores; el diff mensual = variación NFP
    # Usar 3-month MA para evitar revisiones masivas (-50K típicamente 3 semanas después)
    df = _fred("PAYEMS")
    if df is not None and len(df) >= 5:
        changes = df.diff().dropna()
        
        # Calcular promedio de 3 meses en lugar de MoM puro
        if len(changes) >= 3:
            nfp_3m_avg = float(changes.iloc[-3:, 0].mean())
            nfp_prev_3m = float(changes.iloc[-6:-3, 0].mean()) if len(changes) >= 6 else float(changes.iloc[-4:-3, 0].mean())
        else:
            nfp_3m_avg = float(changes.iloc[-1, 0])
            nfp_prev_3m = float(changes.iloc[-2, 0]) if len(changes) >= 2 else nfp_3m_avg
        
        # Threshold más amplio para suavizar volatilidad
        d = "↑" if nfp_3m_avg > nfp_prev_3m + 50 else ("↓" if nfp_3m_avg < nfp_prev_3m - 50 else "↔")
        
        # Signal basado en tendencia
        if nfp_3m_avg > 150:
            s = "ALCISTA"   # mercado laboral fuerte
        elif nfp_3m_avg < 75:
            s = "BAJISTA"   # debilitamiento → Fed puede cortar
        else:
            s = "NEUTRAL"
        
        fmt = lambda x: f"+{x:.0f}K" if x >= 0 else f"{x:.0f}K"
        preliminary_warning = "  [PRELIMINAR: se revisa típicamente -50K en 3 semanas]"
        
        out["nfp"] = {
            "name":  "NFP Empleo (3m MA)",
            "value": fmt(nfp_3m_avg),
            "prev":  fmt(nfp_prev_3m),
            "dir": d, "signal": s,
            "note": f"> 150K alcista  |  < 75K bajista{preliminary_warning}",
        }
    else:
        out["nfp"] = _nd("NFP Empleo")

    # ──    # ── PIB EE.UU. (GDP) ──────────────────────────────────────────────────────
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
        
        # Detectar si es rápida, segunda o final lectura (basado en días desde cierre de trimestre)
        from datetime import datetime
        last_gdp_date = df.index[-1].to_pydatetime() if hasattr(df, 'index') else datetime.now()
        days_since = (datetime.now() - last_gdp_date).days
        
        # Si < 35 días, es RÁPIDA; 35-65 días = SEGUNDA; > 65 días = FINAL
        if days_since < 35:
            version_warning = "[RÁPIDA: sujeta a revisión -0.3% típicamente]"
        elif days_since < 65:
            version_warning = "[SEGUNDA LECTURA]"
        else:
            version_warning = "[FINAL]"
        
        out["gdp"] = {
            "name":  "PIB EE.UU.",
            "value": f"{gr_now:+.1f}% anualizado",
            "prev":  f"{gr_prev:+.1f}% (trim. ant.)",
            "dir": d, "signal": s,
            "note": f"> 2.5% alcista  |  < 1.5% zona de riesgo  {version_warning}",
        }
    else:
        out["gdp"] = _nd("PIB EE.UU.")

    #     # ── UMich Consumer Sentiment (UMCSENT) ────────────────────────────────────
    df = _fred("UMCSENT")
    if df is not None and len(df) >= 2:
        v  = float(df.iloc[-1, 0])
        p1 = float(df.iloc[-2, 0])  # mes anterior
        
        # Cambio: usar threshold ±4 puntos (cambio real, no ruido)
        change_1m = v - p1
        d = "↑" if change_1m > 4 else ("↓" if change_1m < -4 else "↔")
        
        # Signal: basado en NIVEL absoluto (más importante que cambio MoM)
        if v > 80:
            s = "ALCISTA"    # consumidor muy optimista
        elif v < 55:
            s = "BAJISTA"    # consumidor muy pesimista
        else:
            s = "NEUTRAL"
        
        # Nota: alertar si cambio reciente es importante
        trend_note = ""
        if change_1m > 4:
            trend_note = "  [Mejorando]"
        elif change_1m < -4:
            trend_note = "  [Empeorando]"
        
        out["umich"] = {
            "name":  "UMich Sentiment",
            "value": f"{v:.1f}",
            "prev":  f"{p1:.1f} (mes ant.)",
            "dir": d, "signal": s,
            "note": f"< 55 pesimista  |  > 80 optimista{trend_note}",
        }
    else:
        out["umich"] = _nd("UMich Sentiment")

        # ── Solicitudes de Desempleo Iniciales (ICSA) ─────────────────────────────
    # ICSA en número de personas (no en miles); usar 4-week MA para suavizar volatilidad
    df = _fred("ICSA")
    if df is not None and len(df) >= 8:  # 8 semanas = ~2 meses de datos
        # Últimas 4 semanas vs 4 semanas previas (evita overlap)
        claims_4w_avg = float(df.iloc[-4:, 0].mean())
        claims_4w_prev = float(df.iloc[-8:-4, 0].mean())
        
        # Direction: cambio significativo > 5% en el promedio
        pct_change = (claims_4w_avg - claims_4w_prev) / claims_4w_prev * 100
        d = "↑" if pct_change > 5 else ("↓" if pct_change < -5 else "↔")
        
        # Signal: basado en NIVEL absoluto
        if claims_4w_avg > 260_000:
            s = "BAJISTA"  # mercado laboral debilitándose
        elif claims_4w_avg < 210_000:
            s = "ALCISTA"  # mercado laboral fuerte
        else:
            s = "NEUTRAL"
        
        fmt = lambda x: f"{x/1000:.0f}K"
        out["initial_claims"] = {
            "name":  "Solicitudes Desempleo (4w MA)",
            "value": fmt(claims_4w_avg),
            "prev":  fmt(claims_4w_prev),
            "dir": d, "signal": s,
            "note": "> 260K debilitamiento  |  < 210K mercado laboral fuerte",
        }
    else:
        out["initial_claims"] = _nd("Solicitudes Desempleo")

        # ── ISM Manufacturing PMI (NAPM) ──────────────────────────────────────
    df = _fred("NAPM")
    if df is not None and len(df) >= 2:
        v = float(df.iloc[-1, 0])
        p = float(df.iloc[-2, 0])
        
        # Direction: threshold ±1.5 puntos (cambio real, no ruido de redondeo)
        d = "↑" if v > p + 1.5 else ("↓" if v < p - 1.5 else "↔")
        
        # Signal: regla 50 es PRIMARIA (expansión vs contracción)
        if v > 50 and p <= 50:
            s = "ALCISTA"  # cruzó de contracción a expansión
        elif v <= 50 and p > 50:
            s = "BAJISTA"  # cruzó de expansión a contracción
        elif v > 50:
            s = "ALCISTA"  # sigue en expansión
        else:
            s = "BAJISTA"  # sigue en contracción
        
        out["ism_pmi"] = {
            "name":  "ISM Manufacturing PMI",
            "value": f"{v:.1f}",
            "prev":  f"{p:.1f} (mes ant.)",
            "dir": d, "signal": s,
            "note": "> 50 expansión  |  < 50 contracción  |  [Nota: Manufactura 11% economía; ver ISM Services]",
        }
    else:
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
