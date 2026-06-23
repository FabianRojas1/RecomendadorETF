"""
news_analyzer.py - Integración con NewsAPI para contexto geopolítico
Análisis de sentimiento básico por palabras clave (sin ML)
"""
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

POSITIVE_WORDS = [
    'surge', 'rally', 'gain', 'gains', 'approval', 'approved', 'record', 'growth',
    'bullish', 'strength', 'beat', 'beats', 'success', 'innovation', 'rise', 'rises',
    'soar', 'soars', 'jump', 'jumps', 'outperform', 'upgrade', 'strong', 'positive',
    'recovery', 'boost', 'expand', 'profit', 'revenue', 'demand', 'breakthrough',
]

NEGATIVE_WORDS = [
    'crash', 'decline', 'loss', 'losses', 'crisis', 'war', 'sanction', 'sanctions',
    'bearish', 'weakness', 'miss', 'misses', 'failure', 'risk', 'risks', 'fall',
    'falls', 'drop', 'drops', 'plunge', 'plunges', 'downgrade', 'weak', 'negative',
    'recession', 'slowdown', 'sell-off', 'selloff', 'concern', 'fears', 'tariff',
    'tariffs', 'inflation', 'stagflation', 'default', 'layoff', 'layoffs',
]


class NewsAnalyzer:
    """
    Fetches news from NewsAPI.org and classifies sentiment
    using keyword counting (no ML required).
    """

    NEWS_API_URL = 'https://newsapi.org/v2/everything'

    def __init__(self, config):
        self.api_key  = config.NEWS_API_KEY
        self.keywords = config.NEWS_KEYWORDS

    # ── Public ────────────────────────────────────────────────────────────────

    def get_news_for_ticker(self, ticker: str, days: int = 7) -> list:
        """
        Returns a list of processed news articles for the given ticker.
        Each item: {title, source, sentiment, url, published_at}
        """
        if not self.api_key:
            logger.warning("NEWS_API_KEY not set; skipping news")
            return []

        kws = self.keywords.get(ticker, [])
        if not kws:
            return []

        articles = []
        # Use the top 2 keywords to stay within the 100 req/day limit
        for kw in kws[:2]:
            fetched = self._fetch(kw, days)
            articles.extend(fetched)

        # Deduplicate by URL
        seen = set()
        unique = []
        for a in articles:
            if a['url'] not in seen:
                seen.add(a['url'])
                unique.append(a)

        # Keep only top 10 per ticker
        return unique[:10]

    def analyze_sentiment(self, text: str) -> str:
        """
        Classify text as 'positive' | 'negative' | 'neutral'.
        Simple keyword counting.
        """
        text_lower = text.lower()
        pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
        neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

        if pos > neg:
            return 'positive'
        elif neg > pos:
            return 'negative'
        return 'neutral'

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch(self, keyword: str, days: int) -> list:
        """Call NewsAPI and return processed articles."""
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        params = {
            'q':        keyword,
            'from':     from_date,
            'sortBy':   'publishedAt',
            'language': 'en',
            'pageSize': 5,
            'apiKey':   self.api_key,
        }

        try:
            resp = requests.get(self.NEWS_API_URL, params=params, timeout=8)
            if resp.status_code != 200:
                logger.warning("NewsAPI status %d for '%s'", resp.status_code, keyword)
                return []

            data = resp.json()
            raw_articles = data.get('articles', [])
            processed = []

            for art in raw_articles:
                title       = art.get('title', '') or ''
                description = art.get('description', '') or ''
                text        = f"{title} {description}"
                sentiment   = self.analyze_sentiment(text)

                # Format published date nicely
                pub_raw = art.get('publishedAt', '')
                try:
                    pub_dt  = datetime.fromisoformat(pub_raw.replace('Z', '+00:00'))
                    delta   = datetime.now(pub_dt.tzinfo) - pub_dt
                    if delta.days == 0:
                        hours = delta.seconds // 3600
                        pub   = f"hace {hours}h" if hours > 0 else "hace menos de 1h"
                    else:
                        pub   = f"hace {delta.days}d"
                except Exception:
                    pub = pub_raw[:10]

                processed.append({
                    'title':        title,
                    'source':       art.get('source', {}).get('name', 'Desconocido'),
                    'sentiment':    sentiment,
                    'url':          art.get('url', ''),
                    'published_at': pub,
                })

            return processed

        except requests.exceptions.Timeout:
            logger.warning("NewsAPI timeout for '%s'", keyword)
            return []
        except Exception as e:
            logger.warning("NewsAPI error for '%s': %s", keyword, e)
            return []
