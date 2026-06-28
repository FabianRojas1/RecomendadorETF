"""
config.py - Configuración centralizada del recomendador de inversiones
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ── Telegram ──────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    # ── News API ───────────────────────────────────────────────────
    NEWS_API_KEY = os.getenv('NEWS_API_KEY')

    # ── Timezone ───────────────────────────────────────────────────
    TIMEZONE = os.getenv('TIMEZONE', 'America/Bogota')

    # ── Paths ──────────────────────────────────────────────────────
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, 'data', 'inversiones.db')
    PORTFOLIO_CSV = os.path.join(BASE_DIR, 'portfolio.csv')
    OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

    # ── Alert thresholds ───────────────────────────────────────────
    PRICE_ALERT_THRESHOLD = 5.0   # % change triggers immediate alert

    # ── Analysis settings ──────────────────────────────────────────
    HISTORY_DAYS = 250            # Days of history to download (SMA200 needs 200+)
    WEEKLY_ANALYSIS_DAY = 'sun'
    WEEKLY_ANALYSIS_HOUR = 19
    WEEKLY_ANALYSIS_MINUTE = 0
    MONITOR_INTERVAL_HOURS = 24

    # ── Trii local tickers → yfinance equivalents ──────────────────
    # Trii lists Colombian depositary receipts; these are the underlying US instruments
    TRII_YFINANCE_MAP = {
        'IUITCO':  'IYW',      # iShares US Technology ETF
        'IUFSCO':  'IYF',      # iShares US Financials ETF
        'IUESCO':  'XLU',      # SPDR Utilities (Essential Services equivalent)
        'CSPXCO':  'SPY',      # S&P 500
        'BACCO':   'BAC',      # Bank of America
        'AAPLCO':  'AAPL',     # Apple Inc.
        # Watchlist — tickers con formato especial
        'IWVL':    'IWVL.L',   # iShares MSCI World Value — London Stock Exchange
        'ETH':     'ETH-USD',  # Ethereum
        'XRPUSDT': 'XRP-USD',  # XRP
        'XLMUSDT': 'XLM-USD',  # Stellar Lumens
    }

    # Fallback COP/USD rate (updated at runtime via yfinance)
    DEFAULT_COP_USD_RATE = 4200.0

    # ── Scoring weights ───────────────────────────────────────────
    WEIGHTS = {
        'moving_averages': 3.0,
        'rsi':             2.0,
        'squeeze':         2.0,
        'adx':             2.5,
        'volume':          2.0,
        'news':            1.5,
    }

    # ── Score thresholds → recommendation ─────────────────────────
    BUY_STRONG  =  25
    BUY         =  15
    BUY_WEAK    =   5
    HOLD_LOWER  =  -4
    SELL_WEAK   =  -5
    SELL        = -15
    SELL_STRONG = -25

    # ── NewsAPI keywords per ticker ───────────────────────────────
    NEWS_KEYWORDS = {
        'XLV':    ['healthcare', 'FDA', 'pharma', 'biotech', 'drug approval'],
        'SPY':    ['S&P 500', 'market rally', 'recession', 'Fed rate', 'economy'],
        'QQQ':    ['nasdaq', 'tech stocks', 'AI', 'semiconductor', 'innovation'],
        'SOXX':   ['semiconductor', 'chip shortage', 'TSMC', 'Intel', 'Taiwan'],
        'VWO':    ['emerging markets', 'BRICS', 'China economy', 'developing'],
        'LIT':    ['lithium', 'battery', 'EV', 'electric vehicle', 'Tesla'],
        'IFRA':   ['infrastructure', 'construction', 'utilities', 'government spending'],
        'BOTZ':   ['robotics', 'automation', 'AI manufacturing', 'factory'],
        'ARTY':   ['artificial intelligence', 'AR', 'augmented reality', 'tech'],
        'PALL':   ['palladium', 'precious metals', 'auto catalyst', 'Russia'],
        'URA':    ['uranium', 'nuclear energy', 'nuclear plant', 'energy'],
        'GLD':    ['gold price', 'safe haven', 'inflation hedge', 'dollar'],
        'PSCE':   ['energy sector', 'oil price', 'natural gas', 'renewable energy'],
        'REMX':   ['rare earth', 'critical minerals', 'China supply chain'],
        'QTUM':   ['quantum computing', 'quantum technology', 'IBM quantum'],
        'ITA':    ['aerospace', 'defense spending', 'military', 'Lockheed'],
        'WTAI':   ['AI stocks', 'machine learning', 'generative AI', 'ChatGPT'],
        'BKCH':   ['blockchain', 'Bitcoin ETF', 'crypto regulation', 'DeFi'],
        'ASML':   ['ASML', 'EUV lithography', 'chip equipment', 'semiconductor'],
        'IUITCO':  ['tech stocks', 'technology sector', 'software', 'cloud'],
        'IUFSCO':  ['financial stocks', 'banks', 'interest rates', 'Fed'],
        'IUESCO':  ['utilities', 'essential services', 'electricity', 'water'],
        'CSPXCO':  ['S&P 500', 'US market', 'stocks', 'Wall Street'],
        'BACCO':   ['Bank of America', 'banks', 'financial results', 'Fed'],
        'AAPLCO':  ['Apple', 'iPhone', 'AAPL earnings', 'App Store'],
        # Watchlist
        'IDU':     ['utilities stocks', 'electricity', 'gas utilities', 'water'],
        'VDC':     ['consumer staples', 'defensive stocks', 'grocery', 'household'],
        'VT':      ['global stocks', 'world market', 'total market', 'equity'],
        'ACWI':    ['global equity', 'world market', 'MSCI ACWI', 'international'],
        'IWVL':    ['value stocks', 'MSCI World Value', 'dividend value', 'quality'],
        'IEFA':    ['international stocks', 'EAFE', 'Europe Japan', 'developed markets'],
        'VEU':     ['international equity', 'ex-US stocks', 'global diversification'],
        'VYMI':    ['international dividends', 'high yield dividend', 'global income'],
        'NLR':     ['nuclear energy', 'uranium', 'nuclear power', 'clean energy'],
        'ETH':     ['Ethereum', 'ETH price', 'smart contracts', 'DeFi', 'crypto'],
        'XRPUSDT': ['XRP', 'Ripple', 'crypto payments', 'SEC Ripple', 'digital payments'],
        'XLMUSDT': ['Stellar', 'XLM', 'Stellar Lumens', 'cross-border payments'],
    }
