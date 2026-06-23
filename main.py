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
from src.data_loader    import DataLoader
from src.indicators     import IndicatorCalculator
from src.scoring        import ScoringEngine
from src.news_analyzer  import NewsAnalyzer
from src.telegram_bot   import send_weekly_report, send_test_message, send_price_alert


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")
NEWS_KEY  = os.getenv("NEWS_API_KEY",        "")


# ── ANÁLISIS SEMANAL ──────────────────────────────────────────────────────────

async def run_weekly_analysis():
    """Descarga datos, calcula indicadores y envía reporte + PDF a Telegram."""
    logger.info("=== Iniciando análisis semanal ===")

    loader       = DataLoader()
    scorer       = ScoringEngine()
    news_a       = NewsAnalyzer(api_key=NEWS_KEY)
    cop_rate     = loader.get_cop_usd_rate()
    portfolio    = loader.load_portfolio()

    logger.info("Tasa COP/USD: %.0f | Activos: %d", cop_rate, len(portfolio))

    recommendations = []
    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        try:
            yf_ticker = loader.get_yf_ticker(ticker)
            df = loader.download_history(yf_ticker, period="2y")

            if df is None or df.empty or len(df) < 60:
                logger.warning("%s: datos insuficientes, omitido", ticker)
                continue

            calc   = IndicatorCalculator(df)
            ind    = calc.calculate()
            values = calc.get_current(ind)

            news   = news_a.get_news_for_ticker(ticker, days=7)
            score_data = scorer.calculate_score(values, news)

            rec = scorer.generate_recommendation(
                ticker=ticker,
                score_data=score_data,
                values=values,
                news_data=news,
                cop_rate=cop_rate,
            )
            # Enriquecer con datos del portafolio
            rec["current_value_cop"] = float(row.get("current_value", 0))
            rec["pct_portfolio"]     = row.get("pct_of_total_portfolio", "")
            rec["asset_subtype"]     = row.get("asset_subtype", "")

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
    Sin necesidad de BD persistente — funciona perfectamente en GitHub Actions.
    """
    logger.info("=== Monitor diario de precios ===")

    loader    = DataLoader()
    cop_rate  = loader.get_cop_usd_rate()
    portfolio = loader.load_portfolio()
    alerts    = 0

    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        try:
            yf_ticker = loader.get_yf_ticker(ticker)
            df = loader.download_history(yf_ticker, period="5d")

            if df is None or len(df) < 2:
                continue

            prev  = float(df["Close"].iloc[-2])
            curr  = float(df["Close"].iloc[-1])
            pct   = (curr - prev) / prev * 100

            if abs(pct) >= 5.0:
                logger.info("ALERTA: %s movió %.1f%%", ticker, pct)
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
        id="weekly_analysis", name="Análisis semanal dominical",
    )
    sched.add_job(
        lambda: asyncio.run(run_daily_monitor()),
        "interval", hours=24,
        id="daily_monitor", name="Monitor diario de precios",
    )

    sched.start()
    logger.info("Scheduler iniciado. Análisis: domingos 19:00 Bogotá | Monitor: cada 24h")
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
    parser.add_argument("--now",     action="store_true", help="Análisis semanal inmediato")
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
