"""
indicators.py — Indicadores técnicos con timeframes mixtos.

  Moving Averages (SMA/EMA) : DIARIO
  RSI 14                    : SEMANAL
  Squeeze (BB + KC)         : SEMANAL
  ADX 14                    : SEMANAL
  Volume (OBV/VWAP/CMF)     : DIARIO
"""
import logging
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)
MIN_DAILY_ROWS = 50
MIN_WEEKLY_ROWS = 15   # 15 semanas mínimo para RSI/ADX semanal


class IndicatorCalculator:

    def __init__(self, df: pd.DataFrame):
        if df is None or df.empty or len(df) < MIN_DAILY_ROWS:
            raise ValueError(f"Insufficient daily data: {len(df) if df is not None else 0} rows (need {MIN_DAILY_ROWS}+)")
        self.df = df.copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    # ── Public ────────────────────────────────────────────────────────────────

    def calculate(self) -> dict:
        df = self.df

        # Daily series
        close_d  = df["Close"]
        high_d   = df["High"]
        low_d    = df["Low"]
        vol_d    = df["Volume"]

        # Weekly resample (OHLCV)
        weekly = df.resample("W").agg({
            "Open":   "first",
            "High":   "max",
            "Low":    "min",
            "Close":  "last",
            "Volume": "sum",
        }).dropna()

        close_w = weekly["Close"]
        high_w  = weekly["High"]
        low_w   = weekly["Low"]
        vol_w   = weekly["Volume"]

        enough_weekly = len(weekly) >= MIN_WEEKLY_ROWS

        ind = {
            "close":  close_d,
            "high":   high_d,
            "low":    low_d,
            "open":   df["Open"],
            "volume": vol_d,
            "n_daily":  len(df),
            "n_weekly": len(weekly),
        }

        # ── DAILY: Moving Averages ────────────────────────────────────────
        ind["sma_50"]  = ta.sma(close_d, length=50)
        ind["sma_200"] = ta.sma(close_d, length=200) if len(df) >= 200 else pd.Series([np.nan]*len(df), index=close_d.index)
        ind["ema_12"]  = ta.ema(close_d, length=12)
        ind["ema_26"]  = ta.ema(close_d, length=26)
        ind["ma_tf"]   = "daily"

        # ── WEEKLY: RSI ───────────────────────────────────────────────────
        if enough_weekly:
            ind["rsi"]    = ta.rsi(close_w, length=14)
            ind["rsi_tf"] = "weekly"
        else:
            logger.warning("Falling back to daily RSI (insufficient weekly data)")
            ind["rsi"]    = ta.rsi(close_d, length=14)
            ind["rsi_tf"] = "daily (fallback)"

        # ── WEEKLY: ADX ───────────────────────────────────────────────────
        if enough_weekly:
            adx_data = self._calc_adx(high_w, low_w, close_w)
            ind["adx_tf"] = "weekly"
        else:
            adx_data = self._calc_adx(high_d, low_d, close_d)
            ind["adx_tf"] = "daily (fallback)"
        ind.update(adx_data)

        # ── WEEKLY: Bollinger + Squeeze ───────────────────────────────────
        if enough_weekly:
            bb_data = self._calc_bbands(close_w)
            sq_state = self._detect_squeeze(bb_data, high_w, low_w, close_w)
            ind["squeeze_tf"] = "weekly"
        else:
            bb_data = self._calc_bbands(close_d)
            sq_state = self._detect_squeeze(bb_data, high_d, low_d, close_d)
            ind["squeeze_tf"] = "daily (fallback)"
        ind.update(bb_data)
        ind["squeeze_state"] = sq_state

        # ── DAILY: Volume ─────────────────────────────────────────────────
        ind["obv"]        = ta.obv(close_d, vol_d)
        ind["obv_signal"] = self._obv_trend(ind["obv"])
        ind["vwap"]       = self._calc_vwap(high_d, low_d, close_d, vol_d)
        ind["vwap_signal"]= self._vwap_position(close_d, ind["vwap"])
        ind["cmf"]        = self._calc_cmf(high_d, low_d, close_d, vol_d)
        ind["vol_tf"]     = "daily"

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
            # Daily
            "close":        last(ind["close"]),
            "sma_50":       last(ind["sma_50"]),
            "sma_200":      last(ind["sma_200"]),
            "ema_12":       last(ind["ema_12"]),
            "ema_26":       last(ind["ema_26"]),
            # Weekly (or fallback daily)
            "rsi":          last(ind["rsi"]),
            "rsi_tf":       ind.get("rsi_tf", ""),
            "adx":          last(ind.get("adx")),
            "plus_di":      last(ind.get("plus_di")),
            "minus_di":     last(ind.get("minus_di")),
            "adx_tf":       ind.get("adx_tf", ""),
            "bb_upper":     last(ind.get("bb_upper")),
            "bb_lower":     last(ind.get("bb_lower")),
            "bb_width":     last(ind.get("bb_width")),
            "squeeze_state":ind.get("squeeze_state", "unknown"),
            "squeeze_tf":   ind.get("squeeze_tf", ""),
            # Daily volume
            "obv_signal":   ind.get("obv_signal", "neutral"),
            "vwap":         last(ind.get("vwap")),
            "vwap_signal":  ind.get("vwap_signal", "neutral"),
            "cmf":          last(ind.get("cmf"), 0.0),
            # Meta
            "n_daily":      ind.get("n_daily", 0),
            "n_weekly":     ind.get("n_weekly", 0),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _calc_adx(self, high, low, close) -> dict:
        try:
            adx_df = ta.adx(high, low, close, length=14)
            if adx_df is None or adx_df.empty:
                raise ValueError("empty")
            cols = adx_df.columns.tolist()
            adx_col  = next((c for c in cols if c.startswith("ADX_")),  None)
            dmp_col  = next((c for c in cols if c.startswith("DMP_")),  None)
            dmn_col  = next((c for c in cols if c.startswith("DMN_")),  None)
            return {
                "adx":      adx_df[adx_col]  if adx_col  else pd.Series(dtype=float),
                "plus_di":  adx_df[dmp_col]  if dmp_col  else pd.Series(dtype=float),
                "minus_di": adx_df[dmn_col]  if dmn_col  else pd.Series(dtype=float),
            }
        except Exception as e:
            logger.debug("ADX calc error: %s", e)
            empty = pd.Series(dtype=float)
            return {"adx": empty, "plus_di": empty, "minus_di": empty}

    def _calc_bbands(self, close) -> dict:
        try:
            bb = ta.bbands(close, length=20, std=2.0)
            if bb is None or bb.empty:
                raise ValueError("empty")
            cols = bb.columns.tolist()
            upper = next((c for c in cols if c.startswith("BBU_")), None)
            lower = next((c for c in cols if c.startswith("BBL_")), None)
            mid   = next((c for c in cols if c.startswith("BBM_")), None)
            bw    = next((c for c in cols if c.startswith("BBB_")), None)
            return {
                "bb_upper":  bb[upper] if upper else pd.Series(dtype=float),
                "bb_lower":  bb[lower] if lower else pd.Series(dtype=float),
                "bb_middle": bb[mid]   if mid   else pd.Series(dtype=float),
                "bb_width":  bb[bw]    if bw    else pd.Series(dtype=float),
            }
        except Exception as e:
            logger.debug("BBands error: %s", e)
            empty = pd.Series(dtype=float)
            return {k: empty for k in ["bb_upper", "bb_lower", "bb_middle", "bb_width"]}

    def _detect_squeeze(self, bb_data: dict, high, low, close) -> str:
        try:
            atr      = ta.atr(high, low, close, length=20)
            ema20    = ta.ema(close, length=20)
            kc_upper = ema20 + 1.5 * atr
            kc_lower = ema20 - 1.5 * atr
            bb_upper = bb_data.get("bb_upper")
            bb_lower = bb_data.get("bb_lower")
            if bb_upper is None or bb_upper.dropna().empty:
                return "unknown"
            cu_bb = float(bb_upper.dropna().iloc[-1])
            cl_bb = float(bb_lower.dropna().iloc[-1])
            cu_kc = float(kc_upper.dropna().iloc[-1])
            cl_kc = float(kc_lower.dropna().iloc[-1])
            bb_now = cu_bb - cl_bb
            idx = -6 if len(bb_upper.dropna()) > 6 else -len(bb_upper.dropna())
            bb_prev = float(bb_upper.dropna().iloc[idx]) - float(bb_lower.dropna().iloc[idx])
            if cu_bb < cu_kc and cl_bb > cl_kc:
                return "compressed"
            elif bb_now > bb_prev * 1.15:
                return "released"
            else:
                return "expanding"
        except Exception as e:
            logger.debug("Squeeze error: %s", e)
            return "unknown"

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
            return pd.Series([np.nan]*len(close), index=close.index)

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
            return result if result is not None else pd.Series([0.0]*len(close), index=close.index)
        except Exception:
            return pd.Series([0.0]*len(close), index=close.index)
