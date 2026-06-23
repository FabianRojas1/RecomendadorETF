"""
scoring.py — Motor de scoring con timeframes mixtos.

Rangos de score total:
  COMPRA FUERTE  : >= +25
  COMPRA         : >= +15
  COMPRA DEBIL   : >= +5
  MANTENER       : -4  a +4
  VENTA DEBIL    : <= -5
  VENTA          : <= -15
  VENTA FUERTE   : <= -25
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Pesos por indicador (máx raw score por indicador: ±8 antes del peso)
WEIGHTS = {
    "moving_averages": 3.0,
    "rsi":             2.0,
    "squeeze":         2.0,
    "adx":             2.5,
    "volume":          2.0,
    "news":            1.5,
}

# Umbrales de acción
THRESHOLDS = {
    "buy_strong":   25,
    "buy":          15,
    "buy_weak":      5,
    "hold_lower":   -4,
    "sell_weak":    -5,
    "sell":        -15,
    "sell_strong": -25,
}


class ScoringEngine:

    def calculate_score(self, values: dict, news_data: list) -> dict:
        """
        Calcula el score total y por componente.

        Args:
            values   : dict de get_current() de IndicatorCalculator
            news_data: lista de artículos de NewsAnalyzer

        Returns:
            {total, components, confidence}
        """
        components = {}
        total = 0.0
        signals_active = 0

        evaluators = [
            ("moving_averages", self._eval_ma,     WEIGHTS["moving_averages"]),
            ("rsi",             self._eval_rsi,    WEIGHTS["rsi"]),
            ("squeeze",         self._eval_squeeze,WEIGHTS["squeeze"]),
            ("adx",             self._eval_adx,    WEIGHTS["adx"]),
            ("volume",          self._eval_volume, WEIGHTS["volume"]),
            ("news",            self._eval_news,   WEIGHTS["news"]),
        ]

        for key, fn, weight in evaluators:
            try:
                raw, detail = fn(values, news_data)
                weighted = raw * weight
                total += weighted
                components[key] = {
                    "raw_score":      raw,
                    "weight":         weight,
                    "weighted_score": round(weighted, 2),
                    "signal":         detail.get("signal", "neutral"),
                    "details":        detail.get("details", ""),
                }
                if abs(raw) >= 1:
                    signals_active += 1
            except Exception as e:
                logger.debug("Evaluator %s error: %s", key, e)
                components[key] = {"raw_score": 0, "weight": weight, "weighted_score": 0,
                                   "signal": "error", "details": str(e)}

        total = round(total, 2)
        confidence_pct = round(signals_active / len(evaluators) * 10)

        return {
            "total":      total,
            "components": components,
            "confidence": {"score": signals_active, "total": len(evaluators), "pct": confidence_pct},
        }

    def generate_recommendation(
        self,
        ticker: str,
        score_data: dict,
        values: dict,
        news_data: list,
        cop_rate: float,
    ) -> dict:
        """Genera el dict completo de recomendación para un ticker."""
        total      = score_data["total"]
        components = score_data["components"]
        confidence = score_data["confidence"]

        action = self._action_from_score(total)

        price_usd   = values.get("close") or 0
        price_cop   = price_usd * cop_rate if price_usd else 0
        target_usd  = self._calc_target(price_usd, action)
        sl_usd      = self._calc_stop_loss(price_usd, action)

        reasons = self._build_reasons(components, values)
        explanation = self._build_explanation(action, total, confidence)

        return {
            "ticker":          ticker,
            "action":          action,
            "score":           total,
            "score_components":components,
            "confidence":      confidence,
            "price_usd":       round(price_usd, 2),
            "price_cop":       round(price_cop, 0),
            "target_usd":      round(target_usd, 2) if target_usd else None,
            "stop_loss_usd":   round(sl_usd, 2)     if sl_usd     else None,
            "explanation":     explanation,
            "reasons":         reasons,
            "news":            news_data[:5],
            # Extras para is_strong_signal en telegram_bot
            "squeeze_state":   values.get("squeeze_state", ""),
            "adx_value":       values.get("adx") or 0,
            "rsi_tf":          values.get("rsi_tf", ""),
            "adx_tf":          values.get("adx_tf", ""),
            "squeeze_tf":      values.get("squeeze_tf", ""),
        }

    # ── Acción ────────────────────────────────────────────────────────────────

    def _action_from_score(self, score: float) -> str:
        t = THRESHOLDS
        if   score >= t["buy_strong"]:   return "COMPRA FUERTE"
        elif score >= t["buy"]:          return "COMPRA"
        elif score >= t["buy_weak"]:     return "COMPRA DEBIL"
        elif score <= t["sell_strong"]:  return "VENTA FUERTE"
        elif score <= t["sell"]:         return "VENTA"
        elif score <= t["sell_weak"]:    return "VENTA DEBIL"
        else:                            return "MANTENER"

    # ── Targets / Stop Loss ───────────────────────────────────────────────────

    def _calc_target(self, price: float, action: str) -> Optional[float]:
        if not price:
            return None
        pct_map = {
            "COMPRA FUERTE": 0.10,
            "COMPRA":        0.08,
            "COMPRA DEBIL":  0.05,
            "VENTA FUERTE": -0.10,
            "VENTA":        -0.08,
            "VENTA DEBIL":  -0.05,
        }
        pct = pct_map.get(action)
        return price * (1 + pct) if pct is not None else None

    def _calc_stop_loss(self, price: float, action: str) -> Optional[float]:
        if not price:
            return None
        pct_map = {
            "COMPRA FUERTE": -0.05,
            "COMPRA":        -0.06,
            "COMPRA DEBIL":  -0.07,
            "VENTA FUERTE":   0.05,
            "VENTA":          0.06,
            "VENTA DEBIL":    0.07,
        }
        pct = pct_map.get(action)
        return price * (1 + pct) if pct is not None else None

    # ── Evaluadores ───────────────────────────────────────────────────────────

    def _eval_ma(self, values: dict, _) -> tuple:
        """Medias Móviles — DIARIO."""
        close   = values.get("close")
        sma50   = values.get("sma_50")
        sma200  = values.get("sma_200")
        ema12   = values.get("ema_12")
        ema26   = values.get("ema_26")

        if not close or not sma50:
            return 0, {"signal": "sin datos", "details": ""}

        score = 0
        notes = []

        if sma50 and close > sma50:
            score += 2; notes.append("Precio > SMA50")
        elif sma50:
            score -= 2; notes.append("Precio < SMA50")

        if sma200 and close > sma200:
            score += 2; notes.append("Precio > SMA200 (bull)")
        elif sma200:
            score -= 2; notes.append("Precio < SMA200 (bear)")

        if sma50 and sma200:
            if sma50 > sma200:
                score += 2; notes.append("Golden Cross")
            else:
                score -= 2; notes.append("Death Cross")

        if ema12 and ema26:
            if ema12 > ema26:
                score += 2; notes.append("EMA12 > EMA26 (momentum alcista)")
            else:
                score -= 2; notes.append("EMA12 < EMA26 (momentum bajista)")

        signal = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        return score, {"signal": signal, "details": " | ".join(notes[:3])}

    def _eval_rsi(self, values: dict, _) -> tuple:
        """RSI 14 — SEMANAL."""
        rsi = values.get("rsi")
        tf  = values.get("rsi_tf", "")
        if rsi is None:
            return 0, {"signal": "sin datos", "details": ""}

        if rsi >= 80:
            score = -8; signal = "sobrecompra extrema"
        elif rsi >= 70:
            score = -4; signal = "sobrecompra"
        elif rsi >= 60:
            score =  2; signal = "alcista"
        elif rsi >= 40:
            score =  0; signal = "neutral"
        elif rsi >= 30:
            score =  4; signal = "sobreventa"
        else:
            score =  8; signal = "sobreventa extrema"

        return score, {"signal": signal, "details": f"RSI {rsi:.1f} ({tf})"}

    def _eval_squeeze(self, values: dict, _) -> tuple:
        """Squeeze Momentum — SEMANAL."""
        sq  = values.get("squeeze_state", "unknown")
        tf  = values.get("squeeze_tf", "")
        bw  = values.get("bb_width")
        adx = values.get("adx") or 0

        MAP = {
            "compressed": (6,  "Compresión — posible explosión"),
            "released":   (8,  "Squeeze liberado — energía en movimiento"),
            "expanding":  (2,  "Expandiendo"),
            "unknown":    (0,  "Sin datos"),
        }
        score, label = MAP.get(sq, (0, "—"))
        detail = f"{label} ({tf})"
        if bw: detail += f" | BB Width {bw:.2f}"

        signal = "strong" if score >= 6 else "neutral" if score > 0 else "bearish"
        return score, {"signal": signal, "details": detail}

    def _eval_adx(self, values: dict, _) -> tuple:
        """ADX — SEMANAL."""
        adx  = values.get("adx")
        pdi  = values.get("plus_di")
        mdi  = values.get("minus_di")
        tf   = values.get("adx_tf", "")

        if adx is None:
            return 0, {"signal": "sin datos", "details": ""}

        # ADX fuerza de tendencia
        if   adx >= 50: trend_score = 8
        elif adx >= 35: trend_score = 6
        elif adx >= 25: trend_score = 4
        elif adx >= 20: trend_score = 2
        else:           trend_score = 0

        # Dirección de la tendencia
        direction = 0
        dir_label = "sin dirección"
        if pdi is not None and mdi is not None:
            if pdi > mdi:
                direction = 1; dir_label = f"+DI {pdi:.1f} > -DI {mdi:.1f} (alcista)"
            else:
                direction = -1; dir_label = f"+DI {pdi:.1f} < -DI {mdi:.1f} (bajista)"

        score  = trend_score * direction
        signal = "strong bullish" if score >= 4 else "bullish" if score > 0 else \
                 "strong bearish" if score <= -4 else "bearish" if score < 0 else "weak trend"

        return score, {"signal": signal, "details": f"ADX {adx:.1f} | {dir_label} ({tf})"}

    def _eval_volume(self, values: dict, _) -> tuple:
        """Volumen (OBV/VWAP/CMF) — DIARIO."""
        obv_s  = values.get("obv_signal",  "neutral")
        vwap_s = values.get("vwap_signal", "neutral")
        cmf    = values.get("cmf", 0.0) or 0.0
        tf     = values.get("vol_tf", "")

        score = 0
        notes = []

        if obv_s == "rising":
            score += 3; notes.append("OBV alcista")
        elif obv_s == "falling":
            score -= 3; notes.append("OBV bajista")

        if vwap_s == "above":
            score += 3; notes.append("Precio > VWAP")
        elif vwap_s == "below":
            score -= 3; notes.append("Precio < VWAP")

        if cmf > 0.1:
            score += 2; notes.append(f"CMF {cmf:.2f} (flujo positivo)")
        elif cmf < -0.1:
            score -= 2; notes.append(f"CMF {cmf:.2f} (flujo negativo)")

        signal = "bullish" if score > 2 else "bearish" if score < -2 else "neutral"
        return score, {"signal": signal, "details": " | ".join(notes) + f" ({tf})"}

    def _eval_news(self, _, news_data: list) -> tuple:
        """Noticias — sentimiento agregado."""
        if not news_data:
            return 0, {"signal": "sin noticias", "details": ""}

        pos = sum(1 for n in news_data if n.get("sentiment") == "positive")
        neg = sum(1 for n in news_data if n.get("sentiment") == "negative")
        total = len(news_data)

        if   pos >= neg * 2 and pos >= 2: score = 6
        elif pos > neg:                   score = 3
        elif neg >= pos * 2 and neg >= 2: score = -6
        elif neg > pos:                   score = -3
        else:                             score = 0

        label = "positivo" if score > 0 else "negativo" if score < 0 else "neutral"
        return score, {"signal": label, "details": f"{pos} positivas / {neg} negativas / {total} total"}

    # ── Textos ────────────────────────────────────────────────────────────────

    def _build_reasons(self, components: dict, values: dict) -> list:
        reasons = []
        for key, comp in components.items():
            sig  = comp.get("signal", "")
            det  = comp.get("details", "")
            wsc  = comp.get("weighted_score", 0)
            if abs(wsc) < 1:
                continue
            icon = "✅" if wsc > 0 else "⚠️"
            reasons.append(f"{icon} {det or sig}")
        return reasons[:6]

    def _build_explanation(self, action: str, score: float, confidence: dict) -> str:
        conf_pct = confidence.get("pct", 0)
        return (
            f"Acción: {action} | Score: {score:+.1f}/40 | "
            f"Confianza: {confidence['score']}/{confidence['total']} indicadores activos"
        )
