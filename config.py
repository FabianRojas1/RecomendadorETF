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

    # ── Analysis settings ──────────────────────────────────────────
    # Historial de precios. El motor LP trabaja en marco MENSUAL:
    # EMA55 mensual necesita ~5 anos y EMA200 mensual ~17 anos de historia,
    # por eso se baja todo el historial disponible ("max"). Cuesta lo mismo:
    # una sola peticion por ticker. HISTORY_DAYS queda como respaldo.
    HISTORY_PERIOD = 'max'
    HISTORY_DAYS = 250            # Respaldo si HISTORY_PERIOD no esta definido
    WEEKLY_ANALYSIS_DAY = 'sun'
    WEEKLY_ANALYSIS_HOUR = 19
    WEEKLY_ANALYSIS_MINUTE = 0

    # ── Trii local tickers → yfinance equivalents ──────────────────
    # Trii lists Colombian depositary receipts; these are the underlying US instruments
    TRII_YFINANCE_MAP = {
        'IUITCO':  'IYW',      # iShares US Technology ETF
        'IUFSCO':  'IYF',      # iShares US Financials ETF
        'IUESCO':  'XLU',      # SPDR Utilities (Essential Services equivalent)
        'CSPXCO':  'SPY',      # S&P 500
        'BACCO':   'BAC',      # Bank of America
        'AAPLCO':  'AAPL',     # Apple Inc.
        # Tickers con formato especial
        'IWVL':    'IWVL.L',   # iShares MSCI World Value — London Stock Exchange
        'IWVLCO':  'IWVL.L',   # iShares MSCI World Value (CDI Trii)
        'BTC':     'BTC-USD',  # Bitcoin
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
        'IWVLCO':  ['value stocks', 'MSCI World Value', 'dividend value', 'quality'],
        'IEFA':    ['international stocks', 'EAFE', 'Europe Japan', 'developed markets'],
        'VEU':     ['international equity', 'ex-US stocks', 'global diversification'],
        'VYMI':    ['international dividends', 'high yield dividend', 'global income'],
        'NLR':     ['nuclear energy', 'uranium', 'nuclear power', 'clean energy'],
        'ICLN':    ['clean energy', 'solar', 'wind energy', 'renewable', 'green energy'],
        'BTC':     ['Bitcoin', 'BTC price', 'crypto market', 'halving', 'institutional crypto'],
        'ETH':     ['Ethereum', 'ETH price', 'smart contracts', 'DeFi', 'crypto'],
        'XRPUSDT': ['XRP', 'Ripple', 'crypto payments', 'SEC Ripple', 'digital payments'],
        'XLMUSDT': ['Stellar', 'XLM', 'Stellar Lumens', 'cross-border payments'],
    }

    # ── Nombres completos de activos ──────────────────────────────────────────
    ASSET_NAMES = {
        # Posiciones Hapi
        'PALL':    'Aberdeen Std Physical Palladium ETF',
        'URA':     'Global X Uranium ETF',
        'BOTZ':    'Global X Robotics & AI ETF',
        'QTUM':    'Defiance Quantum ETF',
        'ITA':     'iShares U.S. Aerospace & Defense ETF',
        'XLV':     'Health Care Select Sector SPDR',
        'LIT':     'Global X Lithium & Battery Tech ETF',
        'WTAI':    'WisdomTree AI and Innovation Fund',
        'PSCE':    'Invesco S&P SmallCap Energy ETF',
        'SOXX':    'iShares Semiconductor ETF',
        'BKCH':    'Global X Blockchain ETF',
        'GLD':     'SPDR Gold Shares',
        'QQQ':     'Invesco QQQ Trust (Nasdaq 100)',
        'ARTY':    'iShares Future AI & Tech ETF',
        'REMX':    'VanEck Rare Earth/Strategic Metals ETF',
        'IFRA':    'iShares U.S. Infrastructure ETF',
        'VWO':     'Vanguard FTSE Emerging Markets ETF',
        'SPY':     'SPDR S&P 500 ETF Trust',
        'ASML':    'ASML Holding N.V.',
        'ICLN':    'iShares Global Clean Energy ETF',
        # Posiciones Trii
        'IUITCO':  'iShares U.S. Technology ETF (via Trii)',
        'IUFSCO':  'iShares U.S. Financials ETF (via Trii)',
        'IUESCO':  'iShares U.S. Utilities ETF (via Trii)',
        'CSPXCO':  'iShares Core S&P 500 ETF (via Trii)',
        'BACCO':   'Bank of America Corporation (via Trii)',
        'AAPLCO':  'Apple Inc. (via Trii)',
        # Posiciones Binance
        'BTC':     'Bitcoin',
        'ETH':     'Ethereum',
        # Watchlist
        'IDU':     'iShares U.S. Utilities ETF',
        'VDC':     'Vanguard Consumer Staples ETF',
        'VT':      'Vanguard Total World Stock ETF',
        'ACWI':    'iShares MSCI ACWI ETF',
        'IWVL':    'iShares MSCI World Value Factor ETF',
        'IWVLCO':  'iShares MSCI World Value Factor ETF',
        'IEFA':    'iShares Core MSCI EAFE ETF',
        'VEU':     'Vanguard FTSE All-World ex-US ETF',
        'VYMI':    'Vanguard Intl High Dividend Yield ETF',
        'NLR':     'VanEck Uranium + Nuclear Energy ETF',
        'XRPUSDT': 'XRP (Ripple)',
        'XLMUSDT': 'Stellar Lumens (XLM)',
    }
