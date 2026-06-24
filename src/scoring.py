"""
scoring.py - Evaluadores orientados a CAMBIOS de tendencia.

  Filosofia: score ALTO = cambio reciente / score BAJO = tendencia establecida.

  Pesos:
    moving_averages  x2.5  EMA 50/200 - proximidad al cruce
    squeeze_adx      x4.0  Pico de valle / pico de montana + ADX
    rsi              x2.0  Agotamiento alcista/bajista + divergencias
    volume           x2.0  Conviccion detras del cambio
    news             x1.5  Sentimiento geopolitico

  Score final: [-40, +40]
    >= +15  COMPRA FUERTE
    +5..+14 COMPRA
    -4..+4  MANTENER
    -5..-14 VENTA
    <= -15  VENTA FUERTE
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

SCORE_CAP = 40.0

WEIGHTS = {
    "moving_averages": 2.5,
    "squeeze_adx":     4.0,
    "rsi":             2.0,
    "volume":          2.0,
    "news":            1.5,
}


class Scorer:

    def score(self, values: dict, news_items: list) -> dict:
        evaluators = {
            "moving_averages": self._eval_ma,
            "squeeze_adx":     self._eval_squeeze_adx,
            "rsi":             self._eval_rsi,
            "volume":          self._eval_volume,
            "news":            self._eval_news,
        }
        breakdown = {}
        raw_total = 0.0
        for key, fn in evaluators.items():
            try:
                raw, detail = fn(values, news_items)
            except Exception as e:
                logger.warning("Evaluador %s error: %s", key, e)
                raw, detail = 0, {"signal": "error", "details": str(e)}
            weighted   = round(raw * WEIGHTS[key], 2)
            raw_total += weighted
            breakdown[key] = {
                "raw":      raw,
                "weight":   WEIGHTS[key],
                "weighted": weighted,
                **detail,
            }
        total  = max(-SCORE_CAP, min(SCORE_CAP, round(raw_total, 2)))
        action = self._action(total)
        return {"score": total, "action": action, "breakdown": breakdown}

    def _action(self, score: float) -> str:
        if   score >= 15:  return "COMPRA FUERTE"
        elif score >= 5:   return "COMPRA DEBIL"
        elif score <= -15: return "VENTA FUERTE"
        elif score <= -5:  return "VENTA DEBIL"
        return "MANTENER"

    # =========================================================================
    # 1. EMA 50/200 - Proximidad + velocidad hacia el cruce
    #
    # Filosofia: el cruce es indicador REZAGADO.
    # Cuando cruza, la tendencia ya lleva semanas establecida.
    # La senal mas valiosa es detectar que el cruce SE ACERCA.
    # =========================================================================

    def _eval_ma(self, values: dict, _: Any) -> tuple:
        gc          = values.get("days_since_golden_cross")
        dc          = values.get("days_since_death_cross")
        gap_pct     = values.get("ema_gap_pct")
        gap_closing = values.get("ema_gap_closing", False)
        gap_vel     = values.get("ema_gap_velocity")
        ema50       = values.get("ema_50")
        ema200      = values.get("ema_200")
        tf          = values.get("ma_tf", "")

        score = 0.0
        notes = []

        if gap_pct is not None:
            abs_gap = abs(gap_pct)
            vel_abs = abs(gap_vel) if gap_vel is not None else 0.0

            if gap_pct < 0 and gap_closing:
                if abs_gap < 0.5:
                    score = 8.0
                    notes.append(f"GOLDEN CROSS INMINENTE gap {gap_pct:.2f}% vel {vel_abs:.2f}pp/10d")
                elif abs_gap < 2.0:
                    score = 6.0 + (1.0 if vel_abs > 1.0 else 0.0)
                    notes.append(f"Aproximacion Golden Cross gap {gap_pct:.2f}% vel {vel_abs:.2f}pp/10d")
                elif abs_gap < 5.0:
                    score = 4.0 + (1.0 if vel_abs > 1.5 else 0.0)
                    notes.append(f"EMA50 acercandose a EMA200 (gap {gap_pct:.2f}%)")
                else:
                    score = 2.0
                    notes.append(f"Gap negativo cerrando lentamente (gap {gap_pct:.2f}%)")

            elif gap_pct > 0 and gap_closing:
                if abs_gap < 0.5:
                    score = -8.0
                    notes.append(f"DEATH CROSS INMINENTE gap {gap_pct:.2f}% vel {vel_abs:.2f}pp/10d")
                elif abs_gap < 2.0:
                    score = -6.0 - (1.0 if vel_abs > 1.0 else 0.0)
                    notes.append(f"Aproximacion Death Cross gap {gap_pct:.2f}% vel {vel_abs:.2f}pp/10d")
                elif abs_gap < 5.0:
                    score = -4.0 - (1.0 if vel_abs > 1.5 else 0.0)
                    notes.append(f"EMA50 acercandose a EMA200 (gap {gap_pct:.2f}%)")
                else:
                    score = -2.0
                    notes.append(f"Gap positivo cerrando lentamente (gap {gap_pct:.2f}%)")

            else:
                have_gc   = gc is not None
                have_dc   = dc is not None
                is_golden = have_gc and (not have_dc or gc <= dc)
                if is_golden:
                    if gc <= 20:
                        score = 3.0
                        notes.append(f"Golden Cross hace {gc}d confirmado (brecha abriendo)")
                    elif gc <= 60:
                        score = 2.0
                        notes.append(f"Tendencia alcista Golden Cross hace {gc}d")
                    else:
                        score = 1.0
                        notes.append(f"EMA50 > EMA200 establecido gap {gap_pct:.2f}%")
                elif have_dc:
                    if dc <= 20:
                        score = -3.0
                        notes.append(f"Death Cross hace {dc}d confirmado (brecha abriendo)")
                    elif dc <= 60:
                        score = -2.0
                        notes.append(f"Tendencia bajista Death Cross hace {dc}d")
                    else:
                        score = -1.0
                        notes.append(f"EMA50 < EMA200 establecido gap {gap_pct:.2f}%")
                else:
                    score = 1.0 if gap_pct > 0 else -1.0
                    notes.append(f"Sin cruce registrado gap {gap_pct:.2f}%")
        else:
            if ema50 and ema200:
                score = 1.0 if ema50 > ema200 else -1.0
                notes.append("EMA50/200 sin historial suficiente")
            else:
                notes.append("EMA50/200 sin datos")

        score = max(-8.0, min(8.0, round(score, 1)))
        signal = "alcista" if score > 0 else "bajista" if score < 0 else "neutral"
        notes.append(f"({tf})")
        return score, {"signal": signal, "details": " | ".join(notes)}

    # =========================================================================
    # 2. Squeeze LazyBear + ADX - Pico de valle / Pico de montana
    # =========================================================================

    def _eval_squeeze_adx(self, values: dict, _: Any) -> tuple:
        sq_state   = values.get("squeeze_state", "unknown")
        sqzm_color = values.get("sqzm_color", "unknown")
        valley_bot = values.get("sqzm_valley_bottom", False)
        mtn_peak   = values.get("sqzm_mountain_peak", False)
        adx        = values.get("adx") or 0.0
        adx_prev   = values.get("adx_prev") or 0.0
        plus_di    = values.get("plus_di") or 0.0
        minus_di   = values.get("minus_di") or 0.0
        di_type    = values.get("di_cross_type", "none")
        di_bars    = values.get("di_cross_bars")
        tf         = values.get("squeeze_tf", "")

        if sq_state == "no_squeeze":
            return 0.0, {
                "signal": "sin setup",
                "details": "Tendencia libre sin compresion previa - Trading Latino no aplica",
            }

        if adx < 15:
            return 0.0, {
                "signal": "lateral",
                "details": f"ADX {adx:.1f} - sin tendencia suficiente",
            }

        adx_rising = (adx_prev > 0) and (adx > adx_prev)
        adx_strong = adx >= 25
        score = 0.0
        notes = []

        if valley_bot:
            base = 7.0
            if adx_strong and adx_rising:
                score = base + 1.0
                notes.append(f"PICO DE VALLE histograma toca fondo y sube ADX {adx:.1f} subiendo confirma")
            elif adx_strong:
                score = base
                notes.append(f"Pico de valle ADX {adx:.1f} fuerte")
            else:
                score = base - 2.0
                notes.append(f"Pico de valle ADX {adx:.1f} debil senal temprana")

        elif mtn_peak:
            base = -7.0
            if adx_strong and adx_rising:
                score = base - 1.0
                notes.append(f"PICO DE MONTANA histograma toca techo y cae ADX {adx:.1f} subiendo confirma")
            elif adx_strong:
                score = base
                notes.append(f"Pico de montana ADX {adx:.1f} fuerte")
            else:
                score = base + 2.0
                notes.append(f"Pico de montana ADX {adx:.1f} debil senal temprana")

        elif di_type == "bullish" and di_bars is not None and di_bars <= 4:
            score = 4.0 if adx_strong else 2.0
            notes.append(f"Cruce alcista DI+ > DI- hace {di_bars} semanas")
        elif di_type == "bearish" and di_bars is not None and di_bars <= 4:
            score = -4.0 if adx_strong else -2.0
            notes.append(f"Cruce bajista DI- > DI+ hace {di_bars} semanas")

        elif sq_state == "compressed":
            score = 1.0 if adx_rising else 0.0
            notes.append(f"Compresion activa presion acumulando ADX {adx:.1f}")

        else:
            if sqzm_color in ("green_strong", "green_weak") and plus_di > minus_di:
                score = 1.0
                notes.append("Impulso alcista establecido (no hay cambio reciente)")
            elif sqzm_color in ("red_strong", "red_weak") and minus_di > plus_di:
                score = -1.0
                notes.append("Impulso bajista establecido (no hay cambio reciente)")

        score = max(-8.0, min(8.0, score))
        notes.append(f"({tf})")
        signal = (
            "cambio alcista" if score >= 6 else
            "alcista"        if score >= 2 else
            "cambio bajista" if score <= -6 else
            "bajista"        if score <= -2 else
            "neutral"
        )
        return score, {"signal": signal, "details": " | ".join(notes)}

    # =========================================================================
    # 3. RSI - Agotamiento de tendencia
    # =========================================================================

    def _eval_rsi(self, values: dict, _: Any) -> tuple:
        rsi      = values.get("rsi")
        rsi_prev = values.get("rsi_prev")
        rsi_div  = values.get("rsi_divergence", "none")
        tf       = values.get("rsi_tf", "")

        if rsi is None:
            return 0.0, {"signal": "sin datos", "details": "RSI no disponible"}

        score = 0.0
        notes = []

        if rsi_prev is not None and rsi_prev >= 70 and rsi < rsi_prev:
            agot = min(8.0, round((rsi_prev - rsi) * 0.6 + 4.0, 1))
            score = -agot
            notes.append(f"AGOTAMIENTO ALCISTA RSI {rsi_prev:.1f}->{rsi:.1f} saliendo de sobrecompra")

        elif rsi_prev is not None and rsi_prev <= 30 and rsi > rsi_prev:
            agot = min(8.0, round((rsi - rsi_prev) * 0.6 + 4.0, 1))
            score = agot
            notes.append(f"AGOTAMIENTO BAJISTA RSI {rsi_prev:.1f}->{rsi:.1f} saliendo de sobreventa")

        elif rsi_div == "bullish":
            score = 5.0
            notes.append("Divergencia alcista precio baja RSI sube (agotamiento bajista)")
        elif rsi_div == "bearish":
            score = -5.0
            notes.append("Divergencia bajista precio sube RSI baja (agotamiento alcista)")

        elif rsi >= 70:
            score = -2.0
            notes.append(f"RSI {rsi:.1f} sobrecompra vigilar agotamiento")
        elif rsi <= 30:
            score = 2.0
            notes.append(f"RSI {rsi:.1f} sobreventa vigilar agotamiento")

        elif rsi_prev is not None:
            if rsi > 50 and rsi_prev < 50:
                score = 3.0
                notes.append(f"RSI cruza sobre 50 ({rsi_prev:.1f}->{rsi:.1f}) momentum alcista")
            elif rsi < 50 and rsi_prev > 50:
                score = -3.0
                notes.append(f"RSI cruza bajo 50 ({rsi_prev:.1f}->{rsi:.1f}) momentum bajista")
            elif rsi > 50:
                score = 1.0
                notes.append(f"RSI {rsi:.1f} sobre 50")
            else:
                score = -1.0
                notes.append(f"RSI {rsi:.1f} bajo 50")
        else:
            score = 1.0 if rsi > 50 else -1.0
            notes.append(f"RSI {rsi:.1f}")

        score = max(-8.0, min(8.0, score))
        notes.append(f"({tf})")
        signal = (
            "agotamiento alcista" if score <= -4 else
            "agotamiento bajista" if score >= 4  else
            "alcista"             if score > 0   else
            "bajista"             if score < 0   else
            "neutral"
        )
        return score, {"signal": signal, "details": " | ".join(notes)}

    # =========================================================================
    # 4. Volumen - Conviccion y fuerza del cambio de tendencia
    #
    # Filosofia: el volumen confirma CONVICCIONES, no tendencias.
    # Un cambio con volumen alto es real. Con volumen bajo es trampa.
    #
    # Señales en orden de prioridad:
    #   1. OBV divergencia    - acumulacion/distribucion oculta (mas poderosa)
    #   2. CMF cruce de cero  - flujo de dinero cambia de manos
    #   3. Ratio U/D          - compradores vs vendedores (ultimos 10 dias)
    #   4. Spike de volumen   - conviccion detras del movimiento actual
    # =========================================================================

    def _eval_volume(self, values: dict, _: Any) -> tuple:
        obv_div   = values.get("obv_divergence", "none")
        obv_sig   = values.get("obv_signal", "neutral")
        cmf       = values.get("cmf") or 0.0
        cmf_prev  = values.get("cmf_prev")
        vol_ratio = values.get("vol_ratio")
        vol_ud    = values.get("vol_ud_ratio")
        tf        = values.get("vol_tf", "")

        score = 0.0
        notes = []

        # 1. OBV Divergencia - senal mas poderosa de cambio
        if obv_div == "bullish":
            score += 4.0
            notes.append("OBV DIVERGENCIA ALCISTA precio baja OBV sube (acumulacion oculta)")
        elif obv_div == "bearish":
            score -= 4.0
            notes.append("OBV DIVERGENCIA BAJISTA precio sube OBV baja (distribucion oculta)")

        # 2. CMF cruce de cero - flujo cambia de manos
        if cmf_prev is not None:
            if cmf > 0 and cmf_prev <= 0:
                score += 3.0
                notes.append(f"CMF cruza positivo ({cmf_prev:.2f}->{cmf:.2f}) compradores toman control")
            elif cmf < 0 and cmf_prev >= 0:
                score -= 3.0
                notes.append(f"CMF cruza negativo ({cmf_prev:.2f}->{cmf:.2f}) vendedores toman control")
            elif cmf > 0.15:
                score += 1.5
                notes.append(f"CMF {cmf:.2f} flujo positivo fuerte")
            elif cmf > 0.05:
                score += 0.5
                notes.append(f"CMF {cmf:.2f} flujo positivo leve")
            elif cmf < -0.15:
                score -= 1.5
                notes.append(f"CMF {cmf:.2f} flujo negativo fuerte")
            elif cmf < -0.05:
                score -= 0.5
                notes.append(f"CMF {cmf:.2f} flujo negativo leve")
            else:
                notes.append(f"CMF {cmf:.2f} neutro")
        else:
            if cmf > 0.1:
                score += 1.0
                notes.append(f"CMF {cmf:.2f} positivo")
            elif cmf < -0.1:
                score -= 1.0
                notes.append(f"CMF {cmf:.2f} negativo")

        # 3. Ratio up-day / down-day (acumulacion vs distribucion)
        if vol_ud is not None:
            if vol_ud > 2.0:
                score += 2.0
                notes.append(f"Ratio U/D {vol_ud:.1f} fuerte acumulacion (compradores dominan)")
            elif vol_ud > 1.5:
                score += 1.0
                notes.append(f"Ratio U/D {vol_ud:.1f} acumulacion moderada")
            elif vol_ud < 0.5:
                score -= 2.0
                notes.append(f"Ratio U/D {vol_ud:.1f} fuerte distribucion (vendedores dominan)")
            elif vol_ud < 0.7:
                score -= 1.0
                notes.append(f"Ratio U/D {vol_ud:.1f} distribucion moderada")
            else:
                notes.append(f"Ratio U/D {vol_ud:.1f} equilibrado")

        # 4. Spike de volumen - conviccion detras del movimiento
        if vol_ratio is not None:
            if vol_ratio > 2.0:
                extra = 1.5 if obv_sig == "rising" else -1.5 if obv_sig == "falling" else 0.0
                score += extra
                direction = "alcista" if obv_sig == "rising" else "bajista" if obv_sig == "falling" else "sin dir"
                notes.append(f"Spike {vol_ratio:.1f}x promedio conviccion {direction}")
            elif vol_ratio > 1.5:
                notes.append(f"Volumen elevado {vol_ratio:.1f}x promedio")
            elif vol_ratio < 0.5:
                score *= 0.7
                notes.append(f"Volumen seco {vol_ratio:.1f}x promedio senal menos confiable")

        score = max(-8.0, min(8.0, round(score, 2)))
        notes.append(f"({tf})")
        signal = (
            "acumulacion"  if score >= 4 else
            "alcista"      if score > 0  else
            "distribucion" if score <= -4 else
            "bajista"      if score < 0  else
            "neutral"
        )
        return score, {"signal": signal, "details": " | ".join(notes)}

    # =========================================================================
    # 5. Noticias - Sentimiento geopolitico
    # =========================================================================

    def _eval_news(self, values: dict, news_items: list) -> tuple:
        if not news_items:
            return 0.0, {"signal": "sin noticias", "details": "NewsAPI sin resultados"}

        pos = neg = neu = 0
        keywords_pos = {
            "rally", "surge", "gain", "bullish", "record", "growth",
            "recovery", "breakout", "beat", "strong",
        }
        keywords_neg = {
            "crash", "plunge", "fall", "bearish", "recession", "war",
            "tariff", "ban", "crisis", "collapse", "decline", "risk",
        }
        for item in news_items:
            text = ((item.get("title") or "") + " " + (item.get("description") or "")).lower()
            p = sum(1 for w in keywords_pos if w in text)
            n = sum(1 for w in keywords_neg if w in text)
            if p > n:   pos += 1
            elif n > p: neg += 1
            else:       neu += 1

        total = pos + neg + neu or 1
        net   = pos - neg
        score = round(max(-5.0, min(5.0, net / total * 5)), 2)
        signal = "positivo" if score > 0.5 else "negativo" if score < -0.5 else "neutral"
        details = f"{pos} positivas / {neg} negativas / {neu} neutrales ({total} articulos)"
        return score, {"signal": signal, "details": details}
