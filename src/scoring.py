"""
scoring.py — Motor de scoring con estrategia Trading Latino integrada.

Lógica de confirmación (semanal):
  COMPRA : Squeeze liberado + histograma VERDE (subiendo) + ADX > 25 + DI+ > DI-
           Apoyado por RSI < 70 y volumen alcista
  VENTA  : Squeeze liberado + histograma ROJO  (bajando) + ADX > 25 + DI- > DI+
           Apoyado por RSI > 30 y volumen bajista

Score total: -40 a +40 (capped). Umbrales:
  COMPRA FUERTE  >= +25 | COMPRA  >= +15 | COMPRA DEBIL  >= +5
  MANTENER       en [-4, +4]
  VENTA DEBIL    <= -5  | VENTA   <= -15 | VENTA FUERTE  <= -25
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

WEIGHTS = {
    "moving_averages": 2.5,
    "squeeze_adx":     4.0,   # Squeeze + ADX como unidad (Trading Latino)
    "rsi":             2.0,
    "volume":          2.0,
    "news":            1.5,
}

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
        evaluators = [
            ("moving_averages", self._eval_ma,          WEIGHTS["moving_averages"]),
            ("squeeze_adx",     self._eval_squeeze_adx, WEIGHTS["squeeze_adx"]),
            ("rsi",             self._eval_rsi,         WEIGHTS["rsi"]),
            ("volume",          self._eval_volume,      WEIGHTS["volume"]),
            ("news",            self._eval_news,        WEIGHTS["news"]),
        ]

        components = {}
        raw_total  = 0.0
        signals_active = 0

        for key, fn, weight in evaluators:
            try:
                raw, detail = fn(values, news_data)
                weighted    = raw * weight
                raw_total  += weighted
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
                components[key] = {
                    "raw_score": 0, "weight": weight, "weighted_score": 0,
                    "signal": "error", "details": str(e),
                }

        # Cap en ±40 para consistencia con el label
        total = max(-40.0, min(40.0, round(raw_total, 2)))

        return {
            "total":      total,
            "components": components,
            "confidence": {
                "score": signals_active,
                "total": len(evaluators),
                "pct":   round(signals_active / len(evaluators) * 10),
            },
        }

    def generate_recommendation(
        self,
        ticker: str,
        score_data: dict,
        values: dict,
        news_data: list,
        cop_rate: float,
    ) -> dict:
        total      = score_data["total"]
        components = score_data["components"]
        confidence = score_data["confidence"]
        action     = self._action_from_score(total)

        price_usd = values.get("close") or 0
        price_cop = price_usd * cop_rate if price_usd else 0

        return {
            "ticker":           ticker,
            "action":           action,
            "score":            total,
            "score_components": components,
            "confidence":       confidence,
            "price_usd":        round(price_usd, 2),
            "price_cop":        round(price_cop, 0),
            "target_usd":       self._calc_target(price_usd, action),
            "stop_loss_usd":    self._calc_stop_loss(price_usd, action),
            "reasons":          self._build_reasons(components, values),
            "explanation":      self._build_explanation(action, total, confidence),
            "news":             news_data[:5],
            # Extras para is_strong_signal en telegram_bot
            "squeeze_state":    values.get("squeeze_state", ""),
            "sqzm_color":       values.get("sqzm_color", "unknown"),
            "sqzm_valley":      values.get("sqzm_valley", False),
            "sqzm_peak":        values.get("sqzm_peak",   False),
            "adx_value":        values.get("adx") or 0,
            "rsi_value":        values.get("rsi") or 0,
            "rsi_tf":           values.get("rsi_tf", ""),
            "adx_tf":           values.get("adx_tf", ""),
            "squeeze_tf":       values.get("squeeze_tf", ""),
        }

    # ── Acción ────────────────────────────────────────────────────────────────

    def _action_from_score(self, score: float) -> str:
        t = THRESHOLDS
        if   score >= t["buy_strong"]:  return "COMPRA FUERTE"
        elif score >= t["buy"]:         return "COMPRA"
        elif score >= t["buy_weak"]:    return "COMPRA DEBIL"
        elif score <= t["sell_strong"]: return "VENTA FUERTE"
        elif score <= t["sell"]:        return "VENTA"
        elif score <= t["sell_weak"]:   return "VENTA DEBIL"
        else:                           return "MANTENER"

    # ── Evaluadores ───────────────────────────────────────────────────────────

    def _eval_ma(self, values: dict, _) -> tuple:
        """Medias Móviles — DIARIO (EMA 10/55 + SMA 50/200)."""
        close  = values.get("close")
        ema10  = values.get("ema_10")
        ema55  = values.get("ema_55")
        sma50  = values.get("sma_50")
        sma200 = values.get("sma_200")

        if not close:
            return 0, {"signal": "sin datos", "details": ""}

        score = 0
        notes = []

        # EMA 10 vs EMA 55 (Trading Latino)
        if ema10 and ema55:
            if ema10 > ema55:
                score += 4; notes.append("EMA10 > EMA55 (alcista)")
            else:
                score -= 4; notes.append("EMA10 < EMA55 (bajista)")

        # Precio vs SMA 200 (tendencia de largo plazo)
        if sma200:
            if close > sma200:
                score += 2; notes.append("Precio > SMA200")
            else:
                score -= 2; notes.append("Precio < SMA200")

        # Golden/Death Cross (SMA 50 vs 200)
        if sma50 and sma200:
            if sma50 > sma200:
                score += 2; notes.append("Golden Cross SMA50/200")
            else:
                score -= 2; notes.append("Death Cross SMA50/200")

        signal = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        return score, {"signal": signal, "details": " | ".join(notes)}

    def _eval_squeeze_adx(self, values: dict, _) -> tuple:
        """
        Squeeze Momentum LazyBear + ADX — SEMANAL.
        Implementa la lógica de Trading Latino para inversión a mediano plazo.

        Puntuación máxima: ±8 (antes del peso 4.0 → ±32 puntos en total)

        Señal COMPRA (Trading Latino):
          Squeeze liberado + histograma VERDE (subiendo) + ADX > 25 + DI+ > DI-
          Bonus si es VALLE (primera barra verde) → entrada ideal

        Señal VENTA:
          Squeeze liberado + histograma ROJO (bajando) + ADX > 25 + DI- > DI+
          Bonus si es PICO (primera barra roja) → entrada ideal
        """
        sq_state   = values.get("squeeze_state",  "unknown")
        sqzm_color = values.get("sqzm_color",     "unknown")
        sqzm_val   = values.get("sqzm_val")
        sqzm_valley= values.get("sqzm_valley",    False)
        sqzm_peak  = values.get("sqzm_peak",      False)
        adx        = values.get("adx")   or 0
        plus_di    = values.get("plus_di")  or 0
        minus_di   = values.get("minus_di") or 0
        tf         = values.get("squeeze_tf", "")

        score = 0
        notes = []
        entry_tag = ""

        # ── 1. Fuerza de tendencia (ADX) ─────────────────────────────────────
        if   adx >= 40: adx_score = 3
        elif adx >= 25: adx_score = 2
        elif adx >= 20: adx_score = 1
        else:           adx_score = 0   # Mercado lateral — no operar

        if adx_score == 0:
            return 0, {
                "signal":  "lateral",
                "details": f"ADX {adx:.1f} < 20 — sin tendencia, esperar ({tf})",
            }

        # ── 2. Dirección de la tendencia (DI+ vs DI-) ─────────────────────
        if plus_di > minus_di:
            trend_dir = 1
            notes.append(f"DI+ {plus_di:.1f} > DI- {minus_di:.1f} (alcista)")
        elif minus_di > plus_di:
            trend_dir = -1
            notes.append(f"DI- {minus_di:.1f} > DI+ {plus_di:.1f} (bajista)")
        else:
            trend_dir = 0

        # ── 3. Histograma Squeeze (LazyBear) ─────────────────────────────────
        sqzm_score = 0

        if sq_state in ("released", "expanding"):
            # Histograma verde (momentum alcista)
            if sqzm_color == "green_strong":
                sqzm_score = 4
                notes.append("SQZM histograma verde subiendo")
            elif sqzm_color == "green_weak":
                sqzm_score = 2
                notes.append("SQZM histograma verde debilitando")
            # Histograma rojo (momentum bajista)
            elif sqzm_color == "red_strong":
                sqzm_score = -4
                notes.append("SQZM histograma rojo bajando")
            elif sqzm_color == "red_weak":
                sqzm_score = -2
                notes.append("SQZM histograma rojo debilitando")

            # Bonus por entrada de valle/pico (Trading Latino)
            if sqzm_valley and sqzm_score > 0:
                sqzm_score += 1
                entry_tag = " | ENTRADA VALLE ⚡ (señal Trading Latino)"
            elif sqzm_peak and sqzm_score < 0:
                sqzm_score -= 1
                entry_tag = " | ENTRADA PICO ⚡ (señal Trading Latino)"

        elif sq_state == "compressed":
            notes.append("SQZM comprimido — esperando liberación")
            sqzm_score = 0   # Presión acumulada, aún no es señal

        # ── 4. Score final = ADX confirma dirección × histograma ─────────────
        # Solo sumar si ADX y histograma apuntan en la misma dirección
        if (sqzm_score > 0 and trend_dir >= 0) or (sqzm_score < 0 and trend_dir <= 0):
            score = (adx_score + abs(sqzm_score)) * trend_dir
        else:
            # Divergencia ADX/histograma → señal débil
            score = round((adx_score + abs(sqzm_score)) * trend_dir * 0.3)
            notes.append("Divergencia DI/histograma")

        score = max(-8, min(8, score))  # Cap por componente

        notes.append(f"ADX {adx:.1f} ({tf})")
        if entry_tag:
            notes.append(entry_tag)

        signal = (
            "strong bullish" if score >= 5 else
            "bullish"        if score >= 2 else
            "strong bearish" if score <= -5 else
            "bearish"        if score <= -2 else
            "neutral"
        )

        return score, {"signal": signal, "details": " | ".join(notes)}

    def _eval_rsi(self, values: dict, _) -> tuple:
        """
        RSI 14 — SEMANAL. Actúa como filtro y confirmación:
          - RSI muy sobrecomprado (>70): reduce señal de compra
          - RSI muy sobrevendido (<30): reduce señal de venta
          - RSI en zona media: apoya la dirección del Squeeze
        """
        rsi = values.get("rsi")
        tf  = values.get("rsi_tf", "")

        if rsi is None:
            return 0, {"signal": "sin datos", "details": ""}

        if   rsi >= 75: score, signal = -4, "sobrecompra extrema — evitar COMPRA"
        elif rsi >= 70: score, signal =  0, "sobrecompra — precaución"
        elif rsi >= 60: score, signal =  3, "zona alcista"
        elif rsi >= 45: score, signal =  1, "zona neutral-alcista"
        elif rsi >= 35: score, signal = -1, "zona neutral-bajista"
        elif rsi >= 30: score, signal =  0, "sobreventa — precaución"
        else:           score, signal =  4, "sobreventa extrema — evitar VENTA"

        return score, {"signal": signal, "details": f"RSI {rsi:.1f} ({tf})"}

    def _eval_volume(self, values: dict, _) -> tuple:
        """Volumen (OBV / VWAP / CMF) — DIARIO. Confirma dirección."""
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

        score  = max(-8, min(8, score))
        signal = "bullish" if score > 2 else "bearish" if score < -2 else "neutral"
        return score, {"signal": signal, "details": " | ".join(notes) + f" ({tf})"}

    def _eval_news(self, _, news_data: list) -> tuple:
        """Contexto de noticias — sentimiento agregado."""
        if not news_data:
            return 0, {"signal": "sin noticias", "details": ""}

        pos   = sum(1 for n in news_data if n.get("sentiment") == "positive")
        neg   = sum(1 for n in news_data if n.get("sentiment") == "negative")
        total = len(news_data)

        if   pos >= neg * 2 and pos >= 2: score = 5
        elif pos > neg:                   score = 2
        elif neg >= pos * 2 and neg >= 2: score = -5
        elif neg > pos:                   score = -2
        else:                             score = 0

        label = "positivo" if score > 0 else "negativo" if score < 0 else "neutral"
        return score, {
            "signal":  label,
            "details": f"{pos} positivas / {neg} negativas / {total} total",
        }

    # ── Targets y Stop Loss ───────────────────────────────────────────────────

    def _calc_target(self, price: float, action: str) -> Optional[float]:
        if not price: return None
        pct = {"COMPRA FUERTE": .10, "COMPRA": .08, "COMPRA DEBIL": .05,
               "VENTA FUERTE": -.10, "VENTA": -.08, "VENTA DEBIL": -.05}.get(action)
        return round(price * (1 + pct), 2) if pct is not None else None

    def _calc_stop_loss(self, price: float, action: str) -> Optional[float]:
        if not price: return None
        pct = {"COMPRA FUERTE": -.05, "COMPRA": -.06, "COMPRA DEBIL": -.07,
               "VENTA FUERTE":  .05,  "VENTA":  .06,  "VENTA DEBIL":  .07}.get(action)
        return round(price * (1 + pct), 2) if pct is not None else None

    # ── Textos ────────────────────────────────────────────────────────────────

    def _build_reasons(self, components: dict, values: dict) -> list:
        reasons = []
        for key, comp in components.items():
            wsc = comp.get("weighted_score", 0)
            det = comp.get("details", "") or comp.get("signal", "")
            if abs(wsc) < 1: continue
            icon = "+" if wsc > 0 else "-"
            reasons.append(f"[{icon}] {det}")
        return reasons[:6]

    def _build_explanation(self, action: str, score: float, confidence: dict) -> str:
        return (
            f"{action} | Score: {score:+.1f}/40 | "
            f"Confianza: {confidence['score']}/{confidence['total']} indicadores"
        )
