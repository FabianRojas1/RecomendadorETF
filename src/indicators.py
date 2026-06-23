"""
indicators.py — Indicadores técnicos con timeframes mixtos.

  Moving Averages EMA 10/55 + SMA 50/200 : DIARIO
  RSI 14                                  : SEMANAL
  Squeeze Momentum LazyBear (histograma)  : SEMANAL
  ADX 14 + DI+/-                          : SEMANAL
  Volume (OBV / VWAP / CMF)              : DIARIO

Estrategia Trading Latino (confirmación):
  COMPRA : Squeeze liberado + histograma VERDE subiendo (valle) + ADX > 25 + DI+ > DI-
  VENTA  : Squeeze liberado + histograma ROJO bajando  (pico)  + ADX > 25 + DI- > DI+
  Apoyado por RSI semanal (no sobrecomprado/sobrevendido) y volumen diario
"""
import logging
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

MIN_DAILY_ROWS  = 50
MIN_WEEKLY_ROWS = 15   # 15 semanas mínimo para indicadores semanales
SQZM_LENGTH     = 20   # LazyBear default
SQZM_MULT_KC    = 1.5  # Keltner multiplier


class IndicatorCalculator:

    def __init__(self, df: pd.DataFrame):
        if df is None or df.empty or len(df) < MIN_DAILY_ROWS:
            raise ValueError(
                f"Datos insuficientes: {len(df) if df is not None else 0} filas (mínimo {MIN_DAILY_ROWS})"
            )
        self.df = df.copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    # ── API pública ──────────────────────────────────────────────────────────

    def calculate(self) -> dict:
        df      = self.df
        close_d = df["Close"]
        high_d  = df["High"]
        low_d   = df["Low"]
        vol_d   = df["Volume"]

        # Resamplear a semanal (W = fin de semana)
        weekly = df.resample("W").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

        close_w = weekly["Close"]
        high_w  = weekly["High"]
        low_w   = weekly["Low"]
        vol_w   = weekly["Volume"]

        enough_w = len(weekly) >= MIN_WEEKLY_ROWS

        ind = {
            "close": close_d, "high": high_d, "low": low_d,
            "open": df["Open"], "volume": vol_d,
            "n_daily": len(df), "n_weekly": len(weekly),
        }

        # ── DIARIO: Medias Móviles (Trading Latino usa EMA 10 y EMA 55) ────
        ind["ema_10"]  = ta.ema(close_d, length=10)
        ind["ema_55"]  = ta.ema(close_d, length=55)
        ind["sma_50"]  = ta.sma(close_d, length=50)
        ind["sma_200"] = ta.sma(close_d, length=200) if len(df) >= 200 \
                         else pd.Series([np.nan] * len(df), index=close_d.index)
        ind["ma_tf"] = "daily"

        # ── SEMANAL: RSI 14 ─────────────────────────────────────────────────
        if enough_w:
            ind["rsi"]    = ta.rsi(close_w, length=14)
            ind["rsi_tf"] = "weekly"
        else:
            ind["rsi"]    = ta.rsi(close_d, length=14)
            ind["rsi_tf"] = "daily (fallback)"

        # ── SEMANAL: ADX 14 ─────────────────────────────────────────────────
        if enough_w:
            adx_data = self._calc_adx(high_w, low_w, close_w)
            ind["adx_tf"] = "weekly"
        else:
            adx_data = self._calc_adx(high_d, low_d, close_d)
            ind["adx_tf"] = "daily (fallback)"
        ind.update(adx_data)

        # ── SEMANAL: Squeeze Momentum LazyBear (histograma + estado) ────────
        if enough_w:
            sq_data = self._calc_squeeze_lazybear(high_w, low_w, close_w)
            ind["squeeze_tf"] = "weekly"
        else:
            sq_data = self._calc_squeeze_lazybear(high_d, low_d, close_d)
            ind["squeeze_tf"] = "daily (fallback)"
        ind.update(sq_data)

        # ── DIARIO: Volumen (OBV / VWAP / CMF) ──────────────────────────────
        ind["obv"]         = ta.obv(close_d, vol_d)
        ind["obv_signal"]  = self._obv_trend(ind["obv"])
        ind["vwap"]        = self._calc_vwap(high_d, low_d, close_d, vol_d)
        ind["vwap_signal"] = self._vwap_position(close_d, ind["vwap"])
        ind["cmf"]         = self._calc_cmf(high_d, low_d, close_d, vol_d)
        ind["vol_tf"]      = "daily"

        return ind

    def get_current(self, ind: dict) -> dict:
        """Extrae el último valor escalar de cada serie."""
        def last(s, default=None):
            try:
                if hasattr(s, "iloc"):
                    v = s.dropna()
                    return float(v.iloc[-1]) if not v.empty else default
                return float(s)
            except Exception:
                return default

        return {
            # Diario — precio y MAs
            "close":       last(ind["close"]),
            "ema_10":      last(ind["ema_10"]),
            "ema_55":      last(ind["ema_55"]),
            "sma_50":      last(ind["sma_50"]),
            "sma_200":     last(ind["sma_200"]),
            "ma_tf":       ind.get("ma_tf", ""),
            # Semanal — RSI
            "rsi":         last(ind["rsi"]),
            "rsi_tf":      ind.get("rsi_tf", ""),
            # Semanal — ADX
            "adx":         last(ind.get("adx")),
            "plus_di":     last(ind.get("plus_di")),
            "minus_di":    last(ind.get("minus_di")),
            "adx_tf":      ind.get("adx_tf", ""),
            # Semanal — Squeeze LazyBear
            "squeeze_state":  ind.get("squeeze_state", "unknown"),
            "sqzm_val":       last(ind.get("sqzm_histogram")),
            "sqzm_prev":      ind.get("sqzm_prev"),
            "sqzm_color":     ind.get("sqzm_color", "unknown"),
            "sqzm_valley":    ind.get("sqzm_valley", False),
            "sqzm_peak":      ind.get("sqzm_peak",   False),
            "bb_upper":       last(ind.get("bb_upper")),
            "bb_lower":       last(ind.get("bb_lower")),
            "squeeze_tf":     ind.get("squeeze_tf", ""),
            # Diario — volumen
            "obv_signal":  ind.get("obv_signal", "neutral"),
            "vwap":        last(ind.get("vwap")),
            "vwap_signal": ind.get("vwap_signal", "neutral"),
            "cmf":         last(ind.get("cmf"), 0.0),
            "vol_tf":      ind.get("vol_tf", ""),
            # Meta
            "n_daily":     ind.get("n_daily", 0),
            "n_weekly":    ind.get("n_weekly", 0),
        }

    # ── Squeeze Momentum LazyBear ─────────────────────────────────────────────

    def _calc_squeeze_lazybear(self, high, low, close) -> dict:
        """
        Implementación del TTM Squeeze de LazyBear.

        Estado:
          squeeze_state : "compressed" | "released" | "expanding" | "unknown"
          sqzm_histogram: Series con el valor del histograma (linreg)
          sqzm_color    : "green_strong" | "green_weak" | "red_strong" | "red_weak"
          sqzm_valley   : True si es la primera barra verde tras barras rojas (entrada LONG)
          sqzm_peak     : True si es la primera barra roja tras barras verdes (entrada SHORT)
        """
        try:
            L = SQZM_LENGTH

            # ── Bollinger Bands ──────────────────────────────────────────────
            bb_basis = ta.sma(close, length=L)
            bb_std   = close.rolling(L).std()
            bb_upper = bb_basis + 2.0 * bb_std
            bb_lower = bb_basis - 2.0 * bb_std

            # ── Keltner Channels ─────────────────────────────────────────────
            atr      = ta.atr(high, low, close, length=L)
            kc_basis = ta.ema(close, length=L)
            kc_upper = kc_basis + SQZM_MULT_KC * atr
            kc_lower = kc_basis - SQZM_MULT_KC * atr

            # ── Estado del Squeeze ───────────────────────────────────────────
            # "compressed" = BB dentro de KC = squeeze ON
            squeeze_on  = (bb_upper < kc_upper) & (bb_lower > kc_lower)
            # "released"   = BB acaba de salir de KC
            squeeze_off = ~squeeze_on
            squeeze_release = squeeze_off & squeeze_on.shift(1).fillna(False)

            # Estado actual (última barra)
            sq_now = squeeze_on.dropna().iloc[-1]   if not squeeze_on.dropna().empty  else None
            sq_rel = squeeze_release.dropna()

            if sq_now is True:
                state = "compressed"
            elif sq_now is False:
                # Verificar si hace poco se liberó (últimas 3 barras)
                recent_release = sq_rel.iloc[-3:].any() if len(sq_rel) >= 3 else False
                state = "released" if recent_release else "expanding"
            else:
                state = "unknown"

            # ── Histograma LazyBear ──────────────────────────────────────────
            # val = linreg(close - avg(avg(highest_high, lowest_low), sma20), L, 0)
            highest = high.rolling(L).max()
            lowest  = low.rolling(L).min()
            mid_hl  = (highest + lowest) / 2
            sma20   = ta.sma(close, length=L)
            delta   = close - (mid_hl + sma20) / 2
            histogram = ta.linreg(delta, length=L)

            # ── Color del histograma ─────────────────────────────────────────
            h_now  = histogram.dropna().iloc[-1]  if not histogram.dropna().empty  else None
            h_prev = histogram.dropna().iloc[-2]  if len(histogram.dropna()) >= 2  else None

            sqzm_color = "unknown"
            if h_now is not None and h_prev is not None:
                if   h_now >= 0 and h_now >= h_prev: sqzm_color = "green_strong"
                elif h_now >= 0 and h_now <  h_prev: sqzm_color = "green_weak"
                elif h_now <  0 and h_now <= h_prev: sqzm_color = "red_strong"
                elif h_now <  0 and h_now >  h_prev: sqzm_color = "red_weak"

            # ── Valle / Pico (señal de entrada Trading Latino) ───────────────
            # Valle = primera barra verde después de al menos 2 barras rojas
            # Pico  = primera barra roja después de al menos 2 barras verdes
            sqzm_valley = False
            sqzm_peak   = False
            if len(histogram.dropna()) >= 4:
                h_vals = histogram.dropna().values
                # últimas 4 barras
                h3, h2, h1, h0 = h_vals[-4], h_vals[-3], h_vals[-2], h_vals[-1]
                sqzm_valley = (h0 >= 0) and (h1 < 0) and (h2 < 0)
                sqzm_peak   = (h0 <  0) and (h1 >= 0) and (h2 >= 0)

            return {
                "squeeze_state":  state,
                "sqzm_histogram": histogram,
                "sqzm_prev":      float(h_prev) if h_prev is not None else None,
                "sqzm_color":     sqzm_color,
                "sqzm_valley":    sqzm_valley,
                "sqzm_peak":      sqzm_peak,
                "bb_upper":       bb_upper,
                "bb_lower":       bb_lower,
                "kc_upper":       kc_upper,
                "kc_lower":       kc_lower,
            }

        except Exception as e:
            logger.warning("Squeeze LazyBear error: %s", e)
            empty = pd.Series(dtype=float)
            return {
                "squeeze_state": "unknown", "sqzm_histogram": empty,
                "sqzm_prev": None, "sqzm_color": "unknown",
                "sqzm_valley": False, "sqzm_peak": False,
                "bb_upper": empty, "bb_lower": empty,
                "kc_upper": empty, "kc_lower": empty,
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_adx(self, high, low, close) -> dict:
        try:
            adx_df = ta.adx(high, low, close, length=14)
            if adx_df is None or adx_df.empty:
                raise ValueError("empty")
            cols    = adx_df.columns.tolist()
            adx_col = next((c for c in cols if c.startswith("ADX_")),  None)
            dmp_col = next((c for c in cols if c.startswith("DMP_")),  None)
            dmn_col = next((c for c in cols if c.startswith("DMN_")),  None)
            return {
                "adx":      adx_df[adx_col]  if adx_col  else pd.Series(dtype=float),
                "plus_di":  adx_df[dmp_col]  if dmp_col  else pd.Series(dtype=float),
                "minus_di": adx_df[dmn_col]  if dmn_col  else pd.Series(dtype=float),
            }
        except Exception as e:
            logger.debug("ADX error: %s", e)
            empty = pd.Series(dtype=float)
            return {"adx": empty, "plus_di": empty, "minus_di": empty}

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
            if np.isnan(lv):
                return "neutral"
            return "above" if lc > lv * 1.001 else "below" if lc < lv * 0.999 else "at"
        except Exception:
            return "neutral"

    def _calc_cmf(self, high, low, close, volume, length=20):
        try:
            result = ta.cmf(high, low, close, volume, length=length)
            return result if result is not None else pd.Series([0.0] * len(close), index=close.index)
        except Exception:
            return pd.Series([0.0] * len(close), index=close.index)
