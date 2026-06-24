"""
indicators.py - Deteccion de CAMBIOS de tendencia.

  EMA 50/200 + gap de proximidad al cruce : DIARIO   - cruce inminente > cruce ya ocurrido
  RSI 14 + divergencia + rsi_prev         : SEMANAL  - agotamiento de tendencia
  Squeeze LazyBear + pico/valle hist      : SEMANAL  - inflexion de momentum
  ADX 14 + DI +/- + di_cross             : SEMANAL  - fuerza y direccion nueva
  Volume OBV/CMF/ratio U/D               : DIARIO   - conviccion detras del cambio

Filosofia: score ALTO = cambio reciente / score BAJO = tendencia establecida.
"""
import logging
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

MIN_DAILY_ROWS   = 50
MIN_WEEKLY_ROWS  = 15
SQZM_LENGTH      = 20
SQZM_MULT_KC     = 1.5
MIN_SQUEEZE_BARS = 3
SQUEEZE_LOOKBACK = 15


class IndicatorCalculator:

    def __init__(self, df: pd.DataFrame):
        if df is None or df.empty or len(df) < MIN_DAILY_ROWS:
            raise ValueError(f"Datos insuficientes: {len(df) if df is not None else 0} filas")
        self.df = df.copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    # -------------------------------------------------------------------------
    # API publica
    # -------------------------------------------------------------------------

    def calculate(self) -> dict:
        df      = self.df
        close_d = df["Close"]
        high_d  = df["High"]
        low_d   = df["Low"]
        vol_d   = df["Volume"]

        weekly = df.resample("W").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

        close_w  = weekly["Close"]
        high_w   = weekly["High"]
        low_w    = weekly["Low"]
        enough_w = len(weekly) >= MIN_WEEKLY_ROWS

        ind = {
            "close": close_d, "high": high_d, "low": low_d,
            "open": df["Open"], "volume": vol_d,
            "n_daily": len(df), "n_weekly": len(weekly),
        }

        # DIARIO: EMA 50/200 + cruce + gap de proximidad
        ema50  = ta.ema(close_d, length=50)
        ema200 = (ta.ema(close_d, length=200) if len(df) >= 200
                  else pd.Series([np.nan] * len(df), index=close_d.index))
        ind["ema_50"]  = ema50
        ind["ema_200"] = ema200
        ind["ma_tf"]   = "daily"

        gc_bars, dc_bars = self._detect_ema_cross(ema50, ema200)
        ind["days_since_golden_cross"] = gc_bars
        ind["days_since_death_cross"]  = dc_bars

        gap_pct, gap_closing, gap_vel = self._calc_ema_gap(ema50, ema200)
        ind["ema_gap_pct"]      = gap_pct
        ind["ema_gap_closing"]  = gap_closing
        ind["ema_gap_velocity"] = gap_vel

        # SEMANAL: RSI 14 + rsi_prev + divergencia
        if enough_w:
            rsi_series = ta.rsi(close_w, length=14)
            ind["rsi"]            = rsi_series
            ind["rsi_prev"]       = self._series_prev(rsi_series)
            ind["rsi_divergence"] = self._detect_rsi_divergence(close_w, rsi_series)
            ind["rsi_tf"]         = "weekly"
        else:
            rsi_series = ta.rsi(close_d, length=14)
            ind["rsi"]            = rsi_series
            ind["rsi_prev"]       = self._series_prev(rsi_series)
            ind["rsi_divergence"] = "none"
            ind["rsi_tf"]         = "daily (fallback)"

        # SEMANAL: ADX 14 + DI cruce
        if enough_w:
            adx_data = self._calc_adx_extended(high_w, low_w, close_w)
            ind["adx_tf"] = "weekly"
        else:
            adx_data = self._calc_adx_extended(high_d, low_d, close_d)
            ind["adx_tf"] = "daily (fallback)"
        ind.update(adx_data)

        # SEMANAL: Squeeze LazyBear + pico/valle
        if enough_w:
            sq_data = self._calc_squeeze_lazybear(high_w, low_w, close_w)
            ind["squeeze_tf"] = "weekly"
        else:
            sq_data = self._calc_squeeze_lazybear(high_d, low_d, close_d)
            ind["squeeze_tf"] = "daily (fallback)"
        ind.update(sq_data)

        # DIARIO: Volumen orientado a cambio de tendencia
        obv_series          = ta.obv(close_d, vol_d)
        cmf_series          = self._calc_cmf(high_d, low_d, close_d, vol_d)
        ind["obv"]          = obv_series
        ind["obv_signal"]   = self._obv_trend(obv_series)
        ind["obv_divergence"] = self._detect_obv_divergence(close_d, obv_series)
        ind["vwap"]         = self._calc_vwap(high_d, low_d, close_d, vol_d)
        ind["vwap_signal"]  = self._vwap_position(close_d, ind["vwap"])
        ind["cmf"]          = cmf_series
        ind["cmf_prev"]     = self._series_prev(cmf_series)
        ind["vol_ratio"]    = self._calc_vol_ratio(vol_d)
        ind["vol_ud_ratio"] = self._calc_vol_ud_ratio(close_d, vol_d)
        ind["vol_tf"]       = "daily"

        return ind

    def get_current(self, ind: dict) -> dict:
        def last(s, default=None):
            try:
                if hasattr(s, "iloc"):
                    v = s.dropna()
                    return float(v.iloc[-1]) if not v.empty else default
                return float(s) if s is not None else default
            except Exception:
                return default

        return {
            "close":                    last(ind["close"]),
            "ema_50":                   last(ind["ema_50"]),
            "ema_200":                  last(ind["ema_200"]),
            "days_since_golden_cross":  ind.get("days_since_golden_cross"),
            "days_since_death_cross":   ind.get("days_since_death_cross"),
            "ema_gap_pct":              ind.get("ema_gap_pct"),
            "ema_gap_closing":          ind.get("ema_gap_closing", False),
            "ema_gap_velocity":         ind.get("ema_gap_velocity"),
            "ma_tf":                    ind.get("ma_tf", ""),
            "rsi":                      last(ind["rsi"]),
            "rsi_prev":                 ind.get("rsi_prev"),
            "rsi_divergence":           ind.get("rsi_divergence", "none"),
            "rsi_tf":                   ind.get("rsi_tf", ""),
            "adx":                      last(ind.get("adx")),
            "adx_prev":                 ind.get("adx_prev"),
            "plus_di":                  last(ind.get("plus_di")),
            "minus_di":                 last(ind.get("minus_di")),
            "di_cross_type":            ind.get("di_cross_type", "none"),
            "di_cross_bars":            ind.get("di_cross_bars"),
            "adx_tf":                   ind.get("adx_tf", ""),
            "squeeze_state":            ind.get("squeeze_state", "unknown"),
            "sqzm_color":               ind.get("sqzm_color", "unknown"),
            "sqzm_prev_color":          ind.get("sqzm_prev_color", "unknown"),
            "sqzm_valley_bottom":       ind.get("sqzm_valley_bottom", False),
            "sqzm_mountain_peak":       ind.get("sqzm_mountain_peak", False),
            "squeeze_tf":               ind.get("squeeze_tf", ""),
            "obv_signal":               ind.get("obv_signal", "neutral"),
            "obv_divergence":           ind.get("obv_divergence", "none"),
            "vwap":                     last(ind.get("vwap")),
            "vwap_signal":              ind.get("vwap_signal", "neutral"),
            "cmf":                      last(ind.get("cmf"), 0.0),
            "cmf_prev":                 ind.get("cmf_prev"),
            "vol_ratio":                ind.get("vol_ratio"),
            "vol_ud_ratio":             ind.get("vol_ud_ratio"),
            "vol_tf":                   ind.get("vol_tf", ""),
            "n_daily":                  ind.get("n_daily", 0),
            "n_weekly":                 ind.get("n_weekly", 0),
        }

    # -------------------------------------------------------------------------
    # Gap EMA50/200 - proximidad al cruce
    # -------------------------------------------------------------------------

    def _calc_ema_gap(self, ema50, ema200):
        """
        gap_pct     : % (EMA50-EMA200)/EMA200. Negativo=bajista. Positivo=alcista.
        gap_closing : True si el gap se mueve hacia cero (cruce se acerca).
        gap_velocity: cambio del gap en ultimos 10 dias (pp). Positivo=subiendo.
        """
        try:
            valid = ema50.notna() & ema200.notna()
            e50   = ema50[valid]
            e200  = ema200[valid]
            if len(e50) < 10:
                return None, False, None
            gap_series  = (e50 - e200) / e200 * 100
            current_gap = float(gap_series.iloc[-1])
            prev_gap    = float(gap_series.iloc[-10])
            velocity    = current_gap - prev_gap
            closing     = (current_gap < 0 and velocity > 0) or \
                          (current_gap > 0 and velocity < 0)
            return round(current_gap, 3), closing, round(velocity, 3)
        except Exception as e:
            logger.debug("EMA gap error: %s", e)
            return None, False, None

    # -------------------------------------------------------------------------
    # Golden / Death Cross
    # -------------------------------------------------------------------------

    def _detect_ema_cross(self, ema50, ema200):
        """Retorna (dias_desde_golden_cross, dias_desde_death_cross). None si no ocurrio."""
        try:
            valid = ema50.notna() & ema200.notna()
            e50   = ema50[valid]
            e200  = ema200[valid]
            if len(e50) < 2:
                return None, None
            above     = (e50 > e200).astype(int)
            cross     = above.diff()
            gc_events = cross[cross == 1]
            dc_events = cross[cross == -1]
            n         = len(e50)

            def _bars_since(events):
                if events.empty:
                    return None
                last_pos = e50.index.get_indexer(
                    [events.index[-1]], method="nearest")[0]
                return n - 1 - last_pos

            return _bars_since(gc_events), _bars_since(dc_events)
        except Exception as e:
            logger.debug("EMA cross error: %s", e)
            return None, None

    # -------------------------------------------------------------------------
    # RSI divergencia
    # -------------------------------------------------------------------------

    def _detect_rsi_divergence(self, close_w, rsi_series, lookback=8):
        """
        bullish : precio baja, RSI sube -> agotamiento bajista
        bearish : precio sube, RSI baja -> agotamiento alcista
        """
        try:
            c = close_w.dropna().iloc[-lookback:]
            r = rsi_series.dropna().iloc[-lookback:]
            if len(c) < lookback or len(r) < lookback:
                return "none"
            p_slope = float(np.polyfit(range(len(c)), c.values, 1)[0])
            r_slope = float(np.polyfit(range(len(r)), r.values, 1)[0])
            if p_slope < 0 and r_slope > 0:
                return "bullish"
            if p_slope > 0 and r_slope < 0:
                return "bearish"
            return "none"
        except Exception:
            return "none"

    def _series_prev(self, series):
        try:
            clean = series.dropna()
            return float(clean.iloc[-2]) if len(clean) >= 2 else None
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # ADX extendido con cruce DI
    # -------------------------------------------------------------------------

    def _calc_adx_extended(self, high, low, close) -> dict:
        try:
            adx_df  = ta.adx(high, low, close, length=14)
            if adx_df is None or adx_df.empty:
                raise ValueError("empty")
            cols    = adx_df.columns.tolist()
            adx_col = next((c for c in cols if c.startswith("ADX_")), None)
            dmp_col = next((c for c in cols if c.startswith("DMP_")), None)
            dmn_col = next((c for c in cols if c.startswith("DMN_")), None)
            adx_s   = adx_df[adx_col] if adx_col else pd.Series(dtype=float)
            pdi_s   = adx_df[dmp_col] if dmp_col else pd.Series(dtype=float)
            mdi_s   = adx_df[dmn_col] if dmn_col else pd.Series(dtype=float)
            adx_prev = self._series_prev(adx_s)
            di_cross_type, di_cross_bars = self._detect_di_cross(pdi_s, mdi_s)
            return {
                "adx":           adx_s,
                "adx_prev":      adx_prev,
                "plus_di":       pdi_s,
                "minus_di":      mdi_s,
                "di_cross_type": di_cross_type,
                "di_cross_bars": di_cross_bars,
            }
        except Exception as e:
            logger.debug("ADX extended error: %s", e)
            empty = pd.Series(dtype=float)
            return {
                "adx": empty, "adx_prev": None,
                "plus_di": empty, "minus_di": empty,
                "di_cross_type": "none", "di_cross_bars": None,
            }

    def _detect_di_cross(self, pdi, mdi):
        try:
            valid = pdi.notna() & mdi.notna()
            p = pdi[valid]
            m = mdi[valid]
            if len(p) < 2:
                return "none", None
            above = (p > m).astype(int)
            cross = above.diff()
            n     = len(p)
            bull  = cross[cross == 1]
            bear  = cross[cross == -1]

            def _bars(events):
                if events.empty:
                    return None
                pos = p.index.get_indexer([events.index[-1]], method="nearest")[0]
                return n - 1 - pos

            gb = _bars(bull)
            db = _bars(bear)
            if gb is None and db is None:
                return "none", None
            if gb is not None and (db is None or gb <= db):
                return "bullish", gb
            return "bearish", db
        except Exception as e:
            logger.debug("DI cross error: %s", e)
            return "none", None

    # -------------------------------------------------------------------------
    # Squeeze LazyBear + pico/valle
    # -------------------------------------------------------------------------

    def _calc_squeeze_lazybear(self, high, low, close) -> dict:
        """
        squeeze_state:
          compressed  -> BB dentro de KC (presion acumulando)
          released    -> salio de KC + compresion valida previa
          expanding   -> fuera de KC sin compresion reciente valida
          no_squeeze  -> nunca se comprimio (tendencia libre, ej. QTUM)
          unknown     -> datos insuficientes

        sqzm_valley_bottom : red_strong -> red_weak (fondo del valle -> señal alcista)
        sqzm_mountain_peak : green_strong -> green_weak (techo -> señal bajista)
        """
        try:
            L        = SQZM_LENGTH
            bb_basis = ta.sma(close, length=L)
            bb_std   = close.rolling(L).std()
            bb_upper = bb_basis + 2.0 * bb_std
            bb_lower = bb_basis - 2.0 * bb_std
            atr      = ta.atr(high, low, close, length=L)
            kc_basis = ta.ema(close, length=L)
            kc_upper = kc_basis + SQZM_MULT_KC * atr
            kc_lower = kc_basis - SQZM_MULT_KC * atr

            squeeze_on  = (bb_upper < kc_upper) & (bb_lower > kc_lower)
            squeeze_off = ~squeeze_on
            sq_clean    = squeeze_on.dropna()
            sq_now      = bool(sq_clean.iloc[-1]) if not sq_clean.empty else None

            def _max_consec(arr):
                mx = cur = 0
                for v in arr:
                    if v:
                        cur += 1
                        mx = max(mx, cur)
                    else:
                        cur = 0
                return mx

            window = sq_clean.iloc[-SQUEEZE_LOOKBACK:] if len(sq_clean) >= SQUEEZE_LOOKBACK else sq_clean
            had_valid_squeeze = _max_consec(window.values) >= MIN_SQUEEZE_BARS

            if sq_now is True:
                state = "compressed"
            elif sq_now is False:
                if not had_valid_squeeze:
                    state = "no_squeeze"
                else:
                    sq_release     = squeeze_off & squeeze_on.shift(1).fillna(False)
                    recent_release = (
                        sq_release.dropna().iloc[-6:].any()
                        if len(sq_release.dropna()) >= 6
                        else sq_release.dropna().any()
                    )
                    state = "released" if recent_release else "expanding"
            else:
                state = "unknown"

            highest   = high.rolling(L).max()
            lowest    = low.rolling(L).min()
            mid_hl    = (highest + lowest) / 2
            sma20     = ta.sma(close, length=L)
            delta     = close - (mid_hl + sma20) / 2
            histogram = ta.linreg(delta, length=L)
            h_series  = histogram.dropna()

            h0 = float(h_series.iloc[-1]) if len(h_series) >= 1 else None
            h1 = float(h_series.iloc[-2]) if len(h_series) >= 2 else None
            h2 = float(h_series.iloc[-3]) if len(h_series) >= 3 else None

            def _color(cur, prev):
                if cur is None or prev is None:
                    return "unknown"
                if   cur >= 0 and cur >= prev: return "green_strong"
                elif cur >= 0 and cur <  prev: return "green_weak"
                elif cur <  0 and cur <= prev: return "red_strong"
                else:                          return "red_weak"

            sqzm_color      = _color(h0, h1)
            sqzm_prev_color = _color(h1, h2)

            sqzm_mountain_peak = (sqzm_prev_color == "green_strong") and (sqzm_color == "green_weak")
            sqzm_valley_bottom = (sqzm_prev_color == "red_strong")   and (sqzm_color == "red_weak")

            return {
                "squeeze_state":      state,
                "sqzm_histogram":     histogram,
                "sqzm_color":         sqzm_color,
                "sqzm_prev_color":    sqzm_prev_color,
                "sqzm_valley_bottom": sqzm_valley_bottom,
                "sqzm_mountain_peak": sqzm_mountain_peak,
                "bb_upper":           bb_upper,
                "bb_lower":           bb_lower,
                "kc_upper":           kc_upper,
                "kc_lower":           kc_lower,
            }

        except Exception as e:
            logger.warning("Squeeze LazyBear error: %s", e)
            empty = pd.Series(dtype=float)
            return {
                "squeeze_state": "unknown", "sqzm_histogram": empty,
                "sqzm_color": "unknown", "sqzm_prev_color": "unknown",
                "sqzm_valley_bottom": False, "sqzm_mountain_peak": False,
                "bb_upper": empty, "bb_lower": empty,
                "kc_upper": empty, "kc_lower": empty,
            }

    # -------------------------------------------------------------------------
    # Volumen orientado a conviccion del cambio de tendencia
    # -------------------------------------------------------------------------

    def _detect_obv_divergence(self, close, obv, lookback=10) -> str:
        """
        Bullish : precio baja, OBV sube -> acumulacion oculta -> cambio alcista
        Bearish : precio sube, OBV baja -> distribucion oculta -> cambio bajista
        """
        try:
            c = close.dropna().iloc[-lookback:]
            o = obv.dropna().iloc[-lookback:]
            if len(c) < lookback or len(o) < lookback:
                return "none"
            p_slope = float(np.polyfit(range(len(c)), c.values, 1)[0])
            o_slope = float(np.polyfit(range(len(o)), o.values, 1)[0])
            if p_slope < 0 and o_slope > 0:
                return "bullish"
            if p_slope > 0 and o_slope < 0:
                return "bearish"
            return "none"
        except Exception:
            return "none"

    def _calc_vol_ratio(self, volume, short=5, long=20):
        """
        Ratio volumen reciente (5d) / promedio largo (20d).
        > 1.5 = spike de volumen (conviccion detras del movimiento)
        < 0.7 = volumen seco (falta de conviccion)
        """
        try:
            v = volume.dropna()
            if len(v) < long:
                return None
            recent_avg = float(v.iloc[-short:].mean())
            long_avg   = float(v.iloc[-long:].mean())
            return round(recent_avg / long_avg, 2) if long_avg > 0 else None
        except Exception:
            return None

    def _calc_vol_ud_ratio(self, close, volume, lookback=10):
        """
        Ratio volumen en dias alcistas / volumen en dias bajistas (ultimos N dias).
        > 1.5 = acumulacion (compradores mas activos)
        < 0.7 = distribucion (vendedores mas activos)
        """
        try:
            c  = close.dropna()
            v  = volume.dropna()
            df = pd.DataFrame({"close": c, "vol": v}).dropna().iloc[-lookback:]
            if len(df) < 4:
                return None
            df["up"] = df["close"].diff() > 0
            up_vol   = df.loc[df["up"],  "vol"].mean()
            dn_vol   = df.loc[~df["up"], "vol"].mean()
            if dn_vol == 0 or np.isnan(dn_vol):
                return None
            return round(up_vol / dn_vol, 2)
        except Exception:
            return None

    def _obv_trend(self, obv) -> str:
        try:
            if obv is None or len(obv.dropna()) < 10:
                return "neutral"
            recent   = obv.dropna().iloc[-5:].mean()
            previous = obv.dropna().iloc[-10:-5].mean()
            if previous == 0:
                return "neutral"
            pct = (recent - previous) / abs(previous) * 100
            return "rising" if pct > 2 else "falling" if pct < -2 else "neutral"
        except Exception:
            return "neutral"

    def _calc_vwap(self, high, low, close, volume):
        try:
            tp = (high + low + close) / 3
            return (tp * volume).cumsum() / volume.cumsum()
        except Exception:
            return pd.Series([np.nan] * len(close), index=close.index)

    def _vwap_position(self, close, vwap) -> str:
        try:
            lc = float(close.dropna().iloc[-1])
            lv = float(vwap.dropna().iloc[-1])
            return "above" if lc > lv * 1.001 else "below" if lc < lv * 0.999 else "at"
        except Exception:
            return "neutral"

    def _calc_cmf(self, high, low, close, volume, length=20):
        try:
            r = ta.cmf(high, low, close, volume, length=length)
            return r if r is not None else pd.Series([0.0] * len(close), index=close.index)
        except Exception:
            return pd.Series([0.0] * len(close), index=close.index)
