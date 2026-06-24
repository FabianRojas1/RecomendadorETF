"""
main.py — Punto de entrada del recomendador de inversiones.

Modos:
  python main.py           → scheduler daemon (uso local)
  python main.py --now     → análisis semanal inmediato (GitHub Actions)
  python main.py --monitor → monitor de precios diario (GitHub Actions)
  python main.py --test    → prueba de conectividad Telegram
"""
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

# ── Importar módulos del proyecto ──────────────────────────────────────────────
from config             import Config
from src.data_loader    import DataLoader
from src.indicators     import IndicatorCalculator
from src.scoring        import Scorer
from src.news_analyzer  import NewsAnalyzer
from src.telegram_bot   import send_weekly_report, send_test_message, send_price_alert


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")


# ── Helpers de precio ─────────────────────────────────────────────────────────

def _calc_target(price: float, action: str):
    pct = {"COMPRA FUERTE": 0.10, "COMPRA": 0.08, "VENTA FUERTE": -0.10, "VENTA": -0.08}.get(action)
    return price * (1 + pct) if pct and price else None

def _calc_stop_loss(price: float, action: str):
    pct = {"COMPRA FUERTE": -0.05, "COMPRA": -0.06, "VENTA FUERTE": 0.05, "VENTA": 0.06}.get(action)
    return price * (1 + pct) if pct and price else None


# ── ANÁLISIS SEMANAL ──────────────────────────────────────────────────────────

async def run_weekly_analysis():
    """Descarga datos, calcula indicadores y envía reporte + PDF a Telegram."""
    logger.info("=== Iniciando análisis semanal ===")

    config    = Config()
    loader    = DataLoader(config)
    scorer    = Scorer()
    news_a    = NewsAnalyzer(config)
    cop_rate  = loader.get_cop_usd_rate()
    portfolio = loader.load_portfolio()

    logger.info("Tasa COP/USD: %.0f | Activos: %d", cop_rate, len(portfolio))

    recommendations = []
    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        try:
            df = loader.download_history(ticker, period="2y")

            if df is None or df.empty or len(df) < 60:
                logger.warning("%s: datos insuficientes, omitido", ticker)
                continue

            calc   = IndicatorCalculator(df)
            ind    = calc.calculate()
            values = calc.get_current(ind)

            news   = news_a.get_news_for_ticker(ticker, days=7)
            result = scorer.score(values, news)

            score     = result["score"]
            action    = result["action"]
            breakdown = result["breakdown"]

            price_usd = values.get("close") or 0
            price_cop = round(price_usd * cop_rate, 0) if price_usd else 0
            target    = _calc_target(price_usd, action)
            sl        = _calc_stop_loss(price_usd, action)

            n_active   = sum(1 for c in breakdown.values() if abs(c.get("weighted", 0)) >= 0.5)
            confidence = {"score": n_active, "total": len(breakdown)}

            reasons = []
            for comp in breakdown.values():
                w      = comp.get("weighted", 0)
                detail = comp.get("details", "") or comp.get("signal", "")
                if abs(w) >= 1.0 and detail:
                    reasons.append(f"{'[+]' if w > 0 else '[-]'} {detail}")

            # weighted_score alias para compatibilidad con pdf_generator
            score_components = {
                k: {**v, "weighted_score": v.get("weighted", 0)}
                for k, v in breakdown.items()
            }

            rec = {
                "ticker":           ticker,
                "action":           action,
                "score":            score,
                "score_components": score_components,
                "confidence":       confidence,
                "price_usd":        round(price_usd, 2),
                "price_cop":        price_cop,
                "target_usd":       round(target, 2) if target else None,
                "stop_loss_usd":    round(sl, 2)     if sl     else None,
                "reasons":          reasons[:5],
                "news":             news[:5],
                "squeeze_state":    values.get("squeeze_state", ""),
                "adx_value":        values.get("adx") or 0,
                "current_value_cop": float(row.get("current_value", 0)),
                "pct_portfolio":    row.get("pct_of_total_portfolio", ""),
                "asset_subtype":    row.get("asset_subtype", ""),
            }

            recommendations.append(rec)
            loader.save_recommendation(ticker, rec)
            logger.info("%s → %s  (score %.1f)", ticker, rec["action"], rec["score"])

        except Exception as e:
            logger.error("Error procesando %s: %s", ticker, e)

    if not recommendations:
        logger.error("Sin recomendaciones generadas. Abortando.")
        return

    portfolio_total = portfolio["current_value"].astype(float).sum()

    ok = await send_weekly_report(
        recommendations=recommendations,
        portfolio_total_cop=portfolio_total,
        cop_usd_rate=cop_rate,
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
    )
    logger.info("Reporte enviado: %s", "OK" if ok else "FALLO")


# ── MONITOR DIARIO ────────────────────────────────────────────────────────────

async def run_daily_monitor():
    """
    Detecta movimientos de precio > 5% comparando los últimos 2 cierres diarios.
    """
    logger.info("=== Monitor diario de precios ===")

    config    = Config()
    loader    = DataLoader(config)
    cop_rate  = loader.get_cop_usd_rate()
    portfolio = loader.load_portfolio()
    alerts    = 0

    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        try:
            df = loader.download_history(ticker, period="5d")

            if df is None or len(df) < 2:
                continue

            prev = float(df["Close"].iloc[-2])
            curr = float(df["Close"].iloc[-1])
            pct  = (curr - prev) / prev * 100

            if abs(pct) >= 5.0:
                logger.info("ALERTA: %s movio %.1f%%", ticker, pct)
                await send_price_alert(
                    ticker=ticker,
                    prev_close=prev,
                    current_price=curr,
                    pct_change=pct,
                    cop_usd_rate=cop_rate,
                    bot_token=BOT_TOKEN,
                    chat_id=CHAT_ID,
                )
                alerts += 1

        except Exception as e:
            logger.error("Error monitor %s: %s", ticker, e)

    logger.info("Monitor completo — %d alertas enviadas", alerts)


# ── TEST ──────────────────────────────────────────────────────────────────────

async def run_test():
    logger.info("Enviando mensaje de prueba...")
    ok = await send_test_message(BOT_TOKEN, CHAT_ID)
    logger.info("Prueba: %s", "OK" if ok else "FALLO")


# ── SCHEDULER LOCAL (daemon) ──────────────────────────────────────────────────

def run_scheduler():
    """Modo daemon con APScheduler para ejecución local."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
        import time
    except ImportError:
        logger.error("APScheduler no instalado. Para modo local: pip install APScheduler")
        sys.exit(1)

    tz = pytz.timezone(os.getenv("TIMEZONE", "America/Bogota"))
    sched = BackgroundScheduler(timezone=tz)

    sched.add_job(
        lambda: asyncio.run(run_weekly_analysis()),
        "cron", day_of_week="sun", hour=19, minute=0,
        id="weekly_analysis", name="Analisis semanal dominical",
    )
    sched.add_job(
        lambda: asyncio.run(run_daily_monitor()),
        "interval", hours=24,
        id="daily_monitor", name="Monitor diario de precios",
    )

    sched.start()
    logger.info("Scheduler iniciado. Analisis: domingos 19:00 Bogota | Monitor: cada 24h")
    logger.info("Presiona Ctrl+C para detener.")

    try:
        while True:
            import time; time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        logger.info("Scheduler detenido.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Recomendador de Inversiones ETF")
    parser.add_argument("--now",     action="store_true", help="Analisis semanal inmediato")
    parser.add_argument("--monitor", action="store_true", help="Monitor diario de precios")
    parser.add_argument("--test",    action="store_true", help="Test de conectividad Telegram")
    args = parser.parse_args()

    if not BOT_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son requeridos en .env o variables de entorno")
        sys.exit(1)

    if args.now:
        asyncio.run(run_weekly_analysis())
    elif args.monitor:
        asyncio.run(run_daily_monitor())
    elif args.test:
        asyncio.run(run_test())
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
