"""
telegram_bot.py — Envío de reportes a Telegram.

Formato final:
  1. Mensaje corto: solo señales fuertes (score >= ±15 o Squeeze+ADX semanal)
  2. PDF adjunto: análisis completo de los 25 activos
  3. Alertas de precio: mensaje inmediato si movimiento > 5%
"""
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import List, Dict, Any

import pytz

logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    from telegram.error import TelegramError
    TG_OK = True
except ImportError:
    TG_OK = False
    logger.warning("python-telegram-bot not installed")

from .pdf_generator import generate_report_pdf

BOGOTA_TZ = pytz.timezone("America/Bogota")

# ── Umbral de señal fuerte ────────────────────────────────────────────────────
STRONG_THRESHOLD = 15          # |score| >= 15
SQUEEZE_ADX_MIN  = 25          # ADX > 25 + squeeze released = señal fuerte


def _is_strong_signal(rec: dict) -> bool:
    """Devuelve True si el activo califica como señal fuerte."""
    score   = rec.get("score", 0)
    sq      = rec.get("squeeze_state", "")
    adx_val = rec.get("adx_value", 0) or 0
    return abs(score) >= STRONG_THRESHOLD or (sq == "released" and adx_val > SQUEEZE_ADX_MIN)


def _fmt_strong_summary(recommendations: List[dict], portfolio_total: float, cop_rate: float) -> str:
    """Construye el mensaje corto de señales fuertes."""
    now   = datetime.now(BOGOTA_TZ)
    fecha = now.strftime("%A %d/%m/%Y %H:%M")

    strong = [r for r in recommendations if _is_strong_signal(r)]
    compras = sorted([r for r in strong if "COMPRA" in r.get("action","")], key=lambda x: -x.get("score",0))
    ventas  = sorted([r for r in strong if "VENTA"  in r.get("action","")], key=lambda x:  x.get("score",0))

    lines = [
        f"<b>🔔 SEÑALES FUERTES — {fecha}</b>",
        f"<i>Portafolio: COP ${portfolio_total:,.0f}  |  USD/COP: {cop_rate:,.0f}</i>",
        "",
    ]

    if compras:
        lines.append("🟢 <b>COMPRA</b>")
        for r in compras:
            ticker  = r.get("ticker","")
            score   = r.get("score", 0)
            price   = r.get("price_usd") or 0
            target  = r.get("target_usd") or 0
            sl      = r.get("stop_loss_usd") or 0
            sq      = r.get("squeeze_state","")
            adx_v   = r.get("adx_value", 0) or 0
            flag    = " ⚡Squeeze" if (sq == "released" and adx_v > SQUEEZE_ADX_MIN) else ""
            line    = f"  • <b>{ticker}</b>  {score:+.1f}/40  |  ${price:.2f}"
            if target: line += f"  → ${target:.2f}"
            if sl:     line += f"  SL ${sl:.2f}"
            line += flag
            lines.append(line)
        lines.append("")

    if ventas:
        lines.append("🔴 <b>VENTA</b>")
        for r in ventas:
            ticker  = r.get("ticker","")
            score   = r.get("score", 0)
            price   = r.get("price_usd") or 0
            sl      = r.get("stop_loss_usd") or 0
            sq      = r.get("squeeze_state","")
            adx_v   = r.get("adx_value", 0) or 0
            flag    = " ⚡Squeeze" if (sq == "released" and adx_v > SQUEEZE_ADX_MIN) else ""
            line    = f"  • <b>{ticker}</b>  {score:+.1f}/40  |  ${price:.2f}"
            if sl:   line += f"  SL ${sl:.2f}"
            line   += flag
            lines.append(line)
        lines.append("")

    if not compras and not ventas:
        lines.append("ℹ️ Sin señales fuertes esta semana.")
        lines.append("Todos los activos en zona MANTENER.")

    lines.append("\U0001f4ce <i>PDF adjunto con análisis técnico completo.</i>")
    return "\n".join(lines)


async def _send_message(bot: "Bot", chat_id: str, text: str):
    """Envía un mensaje HTML con truncado de seguridad."""
    MAX = 4000
    if len(text) <= MAX:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
        return

    # Dividir por líneas
    chunks, current = [], []
    size = 0
    for line in text.split("\n"):
        lsize = len(line) + 1
        if size + lsize > MAX:
            if current:
                chunks.append("\n".join(current))
            current = [line]; size = lsize
        else:
            current.append(line); size += lsize
    if current:
        chunks.append("\n".join(current))

    for chunk in chunks:
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
        await asyncio.sleep(0.5)



def _classify_sentiment(title: str, description: str) -> str:
    """Clasifica sentimiento por keywords — mismo criterio que _eval_news."""
    KEYWORDS_POS = {
        "rally", "surge", "gain", "bullish", "record", "growth",
        "recovery", "breakout", "beat", "strong", "rise", "soar",
        "outperform", "upgrade", "buy", "accumulate",
    }
    KEYWORDS_NEG = {
        "crash", "plunge", "fall", "bearish", "recession", "war",
        "tariff", "ban", "crisis", "collapse", "decline", "risk",
        "sell", "downgrade", "weak", "loss", "drop", "slump",
    }
    text = ((title or "") + " " + (description or "")).lower()
    p = sum(1 for w in KEYWORDS_POS if w in text)
    n = sum(1 for w in KEYWORDS_NEG if w in text)
    if p > n:   return "positive"
    elif n > p: return "negative"
    return "neutral"


def _fmt_news_summary(recommendations: list) -> str:
    """
    Mensaje de noticias para Telegram.

    Criterios:
      - Solo noticias positivas para COMPRA, negativas para VENTA
      - Sentimiento clasificado por keywords (NewsAPI no lo provee)
      - Se incluye si: 2+ noticias confirman, O score >= 20 con 1+ noticia
      - Neutrales descartadas
    """
    lines = ["📰 <b>NOTICIAS QUE CONFIRMAN SEÑAL</b>", ""]

    relevant = []
    total_with_news = 0
    total_with_confirming = 0

    for rec in recommendations:
        action = rec.get("action", "")
        score  = rec.get("score", 0)
        ticker = rec.get("ticker", "")

        if "MANTENER" in action:
            continue

        # news puede estar en "news" o "news_data" segun como lo guarde el rec
        news = rec.get("news") or rec.get("news_data") or []
        if not news:
            continue

        total_with_news += 1
        is_compra = "COMPRA" in action
        is_venta  = "VENTA"  in action

        confirming = []
        for item in news:
            # Usar campo sentiment si existe; si no, clasificar por keywords
            sent = item.get("sentiment")
            if not sent:
                sent = _classify_sentiment(
                    item.get("title", ""),
                    item.get("description", ""),
                )

            if is_compra and sent == "positive":
                confirming.append(item)
            elif is_venta and sent == "negative":
                confirming.append(item)

        logger.info("Noticias %s: %d totales, %d confirman señal %s (score %.1f)",
                    ticker, len(news), len(confirming), action, score)

        if not confirming:
            continue

        total_with_confirming += 1
        # Criterio: 2+ noticias confirman, O score >= 15 con 1+ noticia
        strong = abs(score) >= 15
        if len(confirming) >= 2 or (strong and len(confirming) >= 1):
            relevant.append({
                "ticker":     ticker,
                "action":     action,
                "score":      score,
                "confirming": confirming,
            })

    logger.info("Noticias resumen: %d tickers con señal tienen noticias, "
                "%d con noticias que confirman, %d pasan el filtro final",
                total_with_news, total_with_confirming, len(relevant))

    if not relevant:
        return (
            "📰 <b>NOTICIAS</b>\n\n"
            "<i>No se encontraron noticias que confirmen señales de compra/venta para hoy.</i>\n"
            f"<i>(Se revisaron {total_with_news} tickers con señal activa)</i>"
        )

    relevant.sort(key=lambda x: -abs(x["score"]))

    for item in relevant:
        ticker = item["ticker"]
        action = item["action"]
        score  = item["score"]
        n_conf = len(item["confirming"])
        icon   = "🟢" if "COMPRA" in action else "🔴"
        plural = "s" if n_conf > 1 else ""

        lines.append(f"{icon} <b>{ticker}</b>  {score:+.1f}/40  ({n_conf} noticia{plural} confirman)")

        for news_item in item["confirming"][:3]:
            title  = (news_item.get("title") or "").strip()
            source = news_item.get("source", {})
            src    = source.get("name", "") if isinstance(source, dict) else str(source)
            url    = (news_item.get("url") or "").strip()
            pub    = news_item.get("published_at", "")
            if len(title) > 90:
                title = title[:87] + "..."
            meta = " | ".join(filter(None, [src, pub]))
            meta_txt = f" <i>{meta}</i>" if meta else ""
            lines.append(f"    • <b>{title}</b>{meta_txt}")
            if url:
                lines.append(f"      🔗 {url}")

        lines.append("")

    lines.append("<i>Solo noticias que confirman señal de compra/venta.</i>")
    return "\n".join(lines)


async def send_weekly_report(
    recommendations: List[Dict[str, Any]],
    portfolio_total_cop: float,
    cop_usd_rate: float,
    bot_token: str,
    chat_id: str,
) -> bool:
    """
    Flujo completo del reporte semanal:
      1. Genera PDF con análisis de todos los activos
      2. Envía mensaje corto con señales fuertes
      3. Adjunta el PDF al chat

    Returns True si todo OK.
    """
    if not TG_OK:
        logger.error("python-telegram-bot not installed")
        return False

    try:
        bot = Bot(token=bot_token)

        # 1. Generar PDF
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="reporte_semanal_")
        pdf_path = tmp.name
        tmp.close()

        pdf_ok = generate_report_pdf(
            recommendations=recommendations,
            portfolio_total_cop=portfolio_total_cop,
            cop_usd_rate=cop_usd_rate,
            output_path=pdf_path,
        )

        # 2. Enviar mensaje corto con señales fuertes
        summary_text = _fmt_strong_summary(recommendations, portfolio_total_cop, cop_usd_rate)
        await _send_message(bot, chat_id, summary_text)
        logger.info("Telegram: resumen de señales enviado")

        # 2b. Enviar noticias que confirman señal (solo si hay contenido relevante)
        news_text = _fmt_news_summary(recommendations)
        if news_text:
            await asyncio.sleep(1)
            await _send_message(bot, chat_id, news_text)
            logger.info("Telegram: noticias confirmadoras enviadas")

        # 3. Adjuntar PDF
        if pdf_ok and os.path.exists(pdf_path):
            fecha = datetime.now(BOGOTA_TZ).strftime("%Y%m%d")
            fname = f"reporte_semanal_{fecha}.pdf"
            with open(pdf_path, "rb") as f:
                await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=fname,
                    caption=f"📊 Análisis completo — {datetime.now(BOGOTA_TZ).strftime('%d/%m/%Y')}",
                )
            logger.info("Telegram: PDF adjunto enviado")
            os.unlink(pdf_path)
        else:
            await _send_message(bot, chat_id,
                                "⚠️ No se pudo generar el PDF. Instala fpdf2: <code>pip install fpdf2</code>")

        return True

    except TelegramError as e:
        logger.error("Telegram error en weekly report: %s", e)
        return False
    except Exception as e:
        logger.exception("Error inesperado en weekly report: %s", e)
        return False


async def send_price_alert(
    ticker: str,
    prev_close: float,
    current_price: float,
    pct_change: float,
    cop_usd_rate: float,
    bot_token: str,
    chat_id: str,
) -> bool:
    """Envía alerta de movimiento de precio > 5%."""
    if not TG_OK:
        return False
    try:
        bot  = Bot(token=bot_token)
        icon = "🚀" if pct_change > 0 else "📉"
        sign = "+" if pct_change > 0 else ""
        text = (
            f"{icon} <b>ALERTA DE PRECIO — {ticker}</b>\n"
            f"Movimiento: <b>{sign}{pct_change:.1f}%</b>\n"
            f"Cierre anterior: ${prev_close:.2f}  →  Precio actual: ${current_price:.2f}\n"
            f"<i>{datetime.now(BOGOTA_TZ).strftime('%d/%m/%Y %H:%M')} (Bogotá)</i>"
        )
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.error("Error enviando alerta %s: %s", ticker, e)
        return False


async def send_test_message(bot_token: str, chat_id: str) -> bool:
    """Envía un mensaje de prueba de conectividad."""
    if not TG_OK:
        return False
    try:
        bot  = Bot(token=bot_token)
        text = (
            "✅ <b>Bot de inversiones conectado</b>\n"
            f"<i>{datetime.now(BOGOTA_TZ).strftime('%d/%m/%Y %H:%M')}</i>\n\n"
            "Funciones activas:\n"
            "• Análisis semanal (domingos 19:00 Bogotá)\n"
            "• Alertasde precio (movimientos > 5%)\n"
            "• PDF con reporte completo de 25 activos"
        )
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.error("Telegram test error: %s", e)
        return False
