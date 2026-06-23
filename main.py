"""
main.py - Punto de entrada del Recomendador de Inversiones
Uso:
  python main.py           → inicia scheduler (corre indefinidamente)
  python main.py --now     → ejecuta análisis completo ahora y envía reporte
  python main.py --test    → verifica configuración y envía mensaje de prueba
"""
import asyncio
import logging
import sys
import time

# ── Config & modules ──────────────────────────────────────────────────────────
from config import Config
from src.data_loader    import DataLoader
from src.indicators     import IndicatorCalculator
from src.scoring        import ScoringEngine
from src.news_analyzer  import NewsAnalyzer
from src.telegram_bot   import TelegramBot
from src.scheduler      import InvestmentScheduler

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s [%(levelname)s] %(name)s — %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def build_components(config: Config):
    """Instantiate all system components."""
    loader  = DataLoader(config)
    scorer  = ScoringEngine(config)
    news    = NewsAnalyzer(config)
    tg      = TelegramBot(config)
    return loader, scorer, news, tg


def validate_config(config: Config):
    """Fail fast if required environment variables are missing."""
    missing = []
    if not config.TELEGRAM_BOT_TOKEN:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not config.TELEGRAM_CHAT_ID:
        missing.append('TELEGRAM_CHAT_ID')
    if not config.NEWS_API_KEY:
        missing.append('NEWS_API_KEY (optional but recommended)')
    if missing:
        for m in missing:
            logger.warning("Missing env var: %s", m)
    return len([m for m in missing if 'optional' not in m]) == 0


# ── Modes ─────────────────────────────────────────────────────────────────────

async def run_test(config, loader, tg):
    """Send a test message to Telegram to verify the bot works."""
    logger.info("Sending test message to Telegram…")
    try:
        await tg.send_startup_message()
    except Exception as e:
        logger.error("Telegram test failed: %s", e)
        logger.error(
            "Verifica TELEGRAM_CHAT_ID, abre el bot en Telegram o agrégalo al chat/grupo.",
        )
        return False

    logger.info("Test message sent. Check your Telegram!")

    # Quick indicator test on SPY
    logger.info("Downloading SPY for a quick indicator test…")
    df = loader.download_history('SPY')
    if not df.empty:
        from src.indicators import IndicatorCalculator
        calc = IndicatorCalculator(df)
        ind  = calc.calculate()
        vals = calc.get_current(ind)
        logger.info(
            "SPY quick check — Close: $%.2f | RSI: %.1f | ADX: %.1f | SMA50: $%.2f",
            vals.get('close', 0),
            vals.get('rsi', 0) or 0,
            vals.get('adx', 0) or 0,
            vals.get('sma_50', 0) or 0,
        )
    else:
        logger.warning("Could not download SPY data")


async def run_now(config, loader, scorer, news, tg):
    """Run a full weekly analysis immediately."""
    portfolio = loader.load_portfolio()
    cop_rate  = loader.get_cop_usd_rate()

    logger.info("Starting immediate full analysis for %d tickers…", len(portfolio))
    results = {}

    for _, row in portfolio.iterrows():
        ticker = row['ticker']
        logger.info("  → %s", ticker)
        try:
            df = loader.download_history(ticker)
            if df.empty:
                logger.warning("    No data for %s", ticker)
                continue
            loader._store_prices(ticker, df)

            calc  = IndicatorCalculator(df)
            ind   = calc.calculate()
            vals  = calc.get_current(ind)
            nws   = news.get_news_for_ticker(ticker)
            score = scorer.calculate_score(vals, nws)
            rec   = scorer.generate_recommendation(ticker, score, vals, nws, cop_rate)

            results[ticker] = rec
            loader.save_recommendation(ticker, rec)

            action = rec['action']
            conf   = rec['confidence']
            total  = rec['score']
            logger.info(
                "    %s → %s (score: %+.1f, conf: %d/9)",
                ticker, action, total, conf,
            )

        except Exception as e:
            logger.error("    Error analyzing %s: %s", ticker, e)
            results[ticker] = None

    valid = {k: v for k, v in results.items() if v}
    logger.info("Analysis complete. Sending Telegram report for %d tickers…", len(valid))

    if valid:
        await tg.send_weekly_report(valid, portfolio, cop_rate)
        logger.info("Report sent!")
    else:
        logger.error("No valid results.")


def run_scheduler(config, loader, scorer, news, tg):
    """Start the background scheduler and keep the process alive."""
    scheduler = InvestmentScheduler(
        config           = config,
        data_loader      = loader,
        indicator_calc_cls = IndicatorCalculator,
        scoring_engine   = scorer,
        news_analyzer    = news,
        telegram_bot     = tg,
    )
    scheduler.start()
    asyncio.run(tg.send_startup_message())

    logger.info("=" * 60)
    logger.info("  Recomendador de Inversiones en ejecución")
    logger.info("  Análisis semanal: Domingos 19:00 (Bogotá)")
    logger.info("  Monitor de precios: cada 24h")
    logger.info("  Presiona Ctrl+C para detener")
    logger.info("=" * 60)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Stopping…")
        scheduler.shutdown()
        logger.info("Goodbye.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    config = Config()

    if not validate_config(config):
        logger.error("Missing required environment variables. Check .env file.")
        sys.exit(1)

    loader, scorer, news, tg = build_components(config)

    if '--test' in sys.argv:
        success = asyncio.run(run_test(config, loader, tg))
        if not success:
            sys.exit(1)

    elif '--now' in sys.argv:
        asyncio.run(run_now(config, loader, scorer, news, tg))

    else:
        run_scheduler(config, loader, scorer, news, tg)
