"""
scheduler.py - APScheduler: monitoreo diario + análisis semanal completo
"""
import asyncio
import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class InvestmentScheduler:
    """
    Wraps APScheduler.
    Jobs:
      - daily_monitor:    every 24h — detect >5% price moves → Telegram alert
      - weekly_analysis:  Sundays 19:00 (Bogotá) — full scoring + Telegram report
    """

    def __init__(self, config, data_loader, indicator_calc_cls,
                 scoring_engine, news_analyzer, telegram_bot):
        self.config      = config
        self.loader      = data_loader
        self.IndCalc     = indicator_calc_cls   # class, not instance
        self.scorer      = scoring_engine
        self.news        = news_analyzer
        self.tg          = telegram_bot
        self.tz          = pytz.timezone(config.TIMEZONE)
        self._scheduler  = BackgroundScheduler(timezone=self.tz)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._scheduler.add_job(
            func     = self._run_daily_monitor,
            trigger  = IntervalTrigger(hours=self.config.MONITOR_INTERVAL_HOURS),
            id       = 'daily_monitor',
            replace_existing = True,
        )
        self._scheduler.add_job(
            func    = self._run_weekly_analysis,
            trigger = CronTrigger(
                day_of_week = self.config.WEEKLY_ANALYSIS_DAY,
                hour        = self.config.WEEKLY_ANALYSIS_HOUR,
                minute      = self.config.WEEKLY_ANALYSIS_MINUTE,
                timezone    = self.tz,
            ),
            id      = 'weekly_analysis',
            replace_existing = True,
        )
        self._scheduler.start()

        next_weekly = self._scheduler.get_job('weekly_analysis').next_run_time
        next_daily  = self._scheduler.get_job('daily_monitor').next_run_time
        logger.info("Scheduler started.")
        logger.info("  Next daily monitor : %s", next_daily)
        logger.info("  Next weekly analysis: %s", next_weekly)

    def shutdown(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")

    def run_analysis_now(self):
        """Trigger a full analysis immediately (for testing / first run)."""
        logger.info("Running immediate analysis...")
        self._run_weekly_analysis()

    # ── Jobs (sync wrappers around async functions) ───────────────────────────

    def _run_daily_monitor(self):
        logger.info("[daily_monitor] Starting — %s", datetime.now().strftime('%Y-%m-%d %H:%M'))
        asyncio.run(self._daily_monitor())

    def _run_weekly_analysis(self):
        logger.info("[weekly_analysis] Starting — %s", datetime.now().strftime('%Y-%m-%d %H:%M'))
        asyncio.run(self._weekly_analysis())

    # ── Async implementations ─────────────────────────────────────────────────

    async def _daily_monitor(self):
        """
        Check for >5% daily price moves and alert via Telegram.
        Does NOT run a full analysis (saves API calls).
        """
        portfolio = self.loader.load_portfolio()

        for _, row in portfolio.iterrows():
            ticker = row['ticker']
            try:
                # Download today's close
                df = self.loader.download_history(ticker)
                if df.empty or len(df) < 2:
                    continue

                # Use DataFrame instead of scalar (MultiIndex-safe)
                close_series = df['Close'].dropna()
                today_close  = float(close_series.iloc[-1])
                prev_close   = float(close_series.iloc[-2])

                if prev_close == 0:
                    continue

                change_pct = (today_close - prev_close) / prev_close * 100

                # Store in DB
                self.loader._store_prices(ticker, df)

                if abs(change_pct) >= self.config.PRICE_ALERT_THRESHOLD:
                    entry_price_cop = float(row.get('entry_price', 0) or 0)
                    logger.warning(
                        "ALERT %s: %+.2f%% change (%.2f → %.2f)",
                        ticker, change_pct, prev_close, today_close,
                    )
                    await self.tg.send_price_alert(
                        ticker, change_pct, today_close, entry_price_cop
                    )
                    self.loader.log_alert(
                        ticker,
                        'price_change',
                        f"{ticker} {change_pct:+.2f}% (${today_close:.2f})",
                    )

            except Exception as e:
                logger.error("daily_monitor error for %s: %s", ticker, e)

    async def _weekly_analysis(self):
        """
        Full analysis:
          1. Download prices for all tickers
          2. Calculate indicators
          3. Fetch news
          4. Score + recommend
          5. Send Telegram report
          6. Save to DB
        """
        portfolio = self.loader.load_portfolio()
        cop_rate  = self.loader.get_cop_usd_rate()

        results = {}

        for _, row in portfolio.iterrows():
            ticker = row['ticker']
            logger.info("Analyzing %s …", ticker)
            try:
                # 1. Prices
                df = self.loader.download_history(ticker)
                if df.empty:
                    logger.warning("No price data for %s — skipping", ticker)
                    continue
                self.loader._store_prices(ticker, df)

                # 2. Indicators
                calc = self.IndCalc(df)
                ind  = calc.calculate()
                vals = calc.get_current(ind)

                # 3. News
                news = self.news.get_news_for_ticker(ticker)

                # 4. Score
                score = self.scorer.calculate_score(vals, news)
                rec   = self.scorer.generate_recommendation(
                    ticker, score, vals, news, cop_rate
                )

                results[ticker] = rec

                # 5. Save
                self.loader.save_recommendation(ticker, rec)

            except Exception as e:
                logger.error("weekly_analysis error for %s: %s", ticker, e)
                results[ticker] = None

        # 6. Send Telegram report
        valid = {k: v for k, v in results.items() if v}
        if valid:
            logger.info("Sending Telegram report for %d tickers", len(valid))
            await self.tg.send_weekly_report(valid, portfolio, cop_rate)
        else:
            logger.error("No valid results to report!")
