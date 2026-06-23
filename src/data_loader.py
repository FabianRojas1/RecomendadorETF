"""
data_loader.py - Carga portafolio CSV, descarga precios de yfinance, gestiona SQLite
"""
import os
import sqlite3
import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class DataLoader:
    def __init__(self, config):
        self.config = config
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        self._init_db()

    # ── Database setup ────────────────────────────────────────────────────────

    def _init_db(self):
        """Create all tables if they don't exist."""
        conn = sqlite3.connect(self.config.DB_PATH)
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT NOT NULL,
                yf_ticker  TEXT,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, date)
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS recommendations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker           TEXT NOT NULL,
                date_analysis    TEXT NOT NULL,
                action           TEXT,
                confidence       INTEGER,
                score_total      REAL,
                explanation_json TEXT,
                news_json        TEXT,
                current_price    REAL,
                current_price_cop REAL,
                target_price     REAL,
                stop_loss        REAL,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT,
                alert_type TEXT,
                message    TEXT,
                sent_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database ready: %s", self.config.DB_PATH)

    # ── Portfolio ─────────────────────────────────────────────────────────────

    def load_portfolio(self) -> pd.DataFrame:
        """Load portfolio.csv and return a clean DataFrame."""
        df = pd.read_csv(self.config.PORTFOLIO_CSV)
        df['entry_date'] = pd.to_datetime(df.get('entry_date'), errors='coerce')
        logger.info("Portfolio loaded: %d positions", len(df))
        return df

    # ── Ticker helpers ────────────────────────────────────────────────────────

    def get_yf_ticker(self, ticker: str) -> str:
        """Map local/Trii ticker to yfinance-compatible ticker."""
        return self.config.TRII_YFINANCE_MAP.get(ticker, ticker)

    # ── Price downloads ───────────────────────────────────────────────────────

    def get_cop_usd_rate(self) -> float:
        """Fetch current COP/USD exchange rate from yfinance (fallback: 4200)."""
        try:
            df = yf.download('COP=X', period='5d', auto_adjust=True, progress=False)
            if not df.empty:
                val = float(df['Close'].dropna().iloc[-1])
                logger.info("COP/USD rate: %.2f", val)
                return val
        except Exception as e:
            logger.warning("Could not fetch COP/USD rate: %s", e)
        return self.config.DEFAULT_COP_USD_RATE

    def download_history(self, ticker: str, period: str = None) -> pd.DataFrame:
        """
        Download price history from yfinance.
        Returns DataFrame with columns [Open, High, Low, Close, Volume].
        Returns empty DataFrame on failure.
        """
        yf_ticker = self.get_yf_ticker(ticker)
        dl_period = period if period else f"{self.config.HISTORY_DAYS}d"
        try:
            df = yf.download(
                yf_ticker,
                period=dl_period,
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                logger.warning("No data returned for %s (yf: %s)", ticker, yf_ticker)
                return pd.DataFrame()

            # yfinance sometimes returns MultiIndex columns when downloading 1 ticker
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.index.name = 'Date'
            logger.info("Downloaded %d days for %s", len(df), ticker)
            return df

        except Exception as e:
            logger.error("Error downloading %s: %s", ticker, e)
            return pd.DataFrame()

    def download_all(self, portfolio: pd.DataFrame) -> dict:
        """Download and store price history for every ticker in the portfolio."""
        price_data = {}
        for _, row in portfolio.iterrows():
            ticker = row['ticker']
            df = self.download_history(ticker)
            if not df.empty:
                price_data[ticker] = df
                self._store_prices(ticker, df)
        return price_data

    def _store_prices(self, ticker: str, df: pd.DataFrame):
        """Upsert price rows into SQLite."""
        yf_ticker = self.get_yf_ticker(ticker)
        conn = sqlite3.connect(self.config.DB_PATH)
        for date, row in df.iterrows():
            try:
                conn.execute('''
                    INSERT OR REPLACE INTO price_history
                        (ticker, yf_ticker, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ticker,
                    yf_ticker,
                    date.strftime('%Y-%m-%d'),
                    float(row.get('Open', 0) or 0),
                    float(row.get('High', 0) or 0),
                    float(row.get('Low',  0) or 0),
                    float(row.get('Close', 0) or 0),
                    float(row.get('Volume', 0) or 0),
                ))
            except Exception as e:
                logger.debug("DB insert error %s %s: %s", ticker, date, e)
        conn.commit()
        conn.close()

    def get_prices_from_db(self, ticker: str, days: int = 250) -> pd.DataFrame:
        """Read price history from SQLite."""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        conn = sqlite3.connect(self.config.DB_PATH)
        df = pd.read_sql_query(
            '''SELECT date, open, high, low, close, volume
               FROM price_history
               WHERE ticker = ? AND date >= ?
               ORDER BY date ASC''',
            conn,
            params=(ticker, since),
        )
        conn.close()
        if df.empty:
            return df
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        return df

    def get_previous_close(self, ticker: str) -> float | None:
        """Return second-to-last close stored for ticker (yesterday's price)."""
        conn = sqlite3.connect(self.config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT close FROM price_history WHERE ticker = ? ORDER BY date DESC LIMIT 2',
            (ticker,),
        )
        rows = cursor.fetchall()
        conn.close()
        if len(rows) >= 2:
            return rows[1][0]
        elif rows:
            return rows[0][0]
        return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_recommendation(self, ticker: str, rec: dict):
        """Persist a recommendation record to SQLite."""
        import json
        conn = sqlite3.connect(self.config.DB_PATH)
        conn.execute('''
            INSERT INTO recommendations
                (ticker, date_analysis, action, confidence, score_total,
                 explanation_json, news_json, current_price, current_price_cop,
                 target_price, stop_loss)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ticker,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            rec.get('action'),
            rec.get('confidence'),
            rec.get('score'),
            json.dumps(rec.get('explanation', {}), ensure_ascii=False),
            json.dumps(rec.get('news', []), ensure_ascii=False),
            rec.get('price'),
            rec.get('price_cop'),
            rec.get('target'),
            rec.get('stop_loss'),
        ))
        conn.commit()
        conn.close()

    def log_alert(self, ticker: str, alert_type: str, message: str):
        """Log an alert to the database."""
        conn = sqlite3.connect(self.config.DB_PATH)
        conn.execute(
            'INSERT INTO alerts (ticker, alert_type, message) VALUES (?, ?, ?)',
            (ticker, alert_type, message),
        )
        conn.commit()
        conn.close()
