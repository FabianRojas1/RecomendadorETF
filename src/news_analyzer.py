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

# Palabras clave para clasificar impacto de noticias macro
MACRO_KEYWORDS_ALTO = [
    'fed rate hike', 'fed cuts rates', 'federal reserve', 'central bank',
    'china tariff', 'us tariff', 'trade war', 'geopolitical crisis',
    'russia ukraine', 'middle east conflict', 'nuclear threat',
    'market crash', 'recession', 'financial crisis', 'bank failure',
]

MACRO_KEYWORDS_MEDIO = [
    'inflation', 'cpi', 'unemployment', 'jobless', 'gdp', 'earnings',
    'interest rates', 'bond yield', 'dollar strength', 'yuan', 'semiconductor',
    'chip shortage', 'supply chain', 'energy prices', 'oil prices',
    'corporate earnings', 'guidance cut',
]

MACRO_KEYWORDS_CONTEXTO = [
    'market', 'stock', 'economic data', 'analyst', 'forecast',
    'consumer', 'business', 'investment', 'portfolio', 'asset',
]

FUENTES_CONFIABLES = {
    'bloomberg', 'reuters', 'financial times', 'cnbc', 'wsj',
    'wall street journal', 'yahoo finance', 'marketwatch', 'seeking alpha',
    'economist', 'ft.com', 'ft', 'bloomberg intelligence',
    'federal reserve', 'bank of america', 'goldman sachs', 'jpmorgan',
}



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

    def get_macro_news(self, days: int = 7, max_results: int = 10) -> list:
        """
        Obtiene noticias macro/geopolíticas de la última semana.
        Retorna sin análisis de sentimiento — deja que el usuario interprete.
        """
        if not self.api_key:
            logger.warning("NEWS_API_KEY not set; skipping macro news")
            return []
        
        keywords = [
            'fed rate', 'federal reserve', 'inflation cpi',
            'unemployment jobs', 'gdp economic',
            'china tariff trade', 'geopolitical crisis',
            'interest rates bond', 'stock market earnings',
        ]
        
        all_articles = []
        for kw in keywords[:6]:  # Máx 6 búsquedas
            fetched = self._fetch(kw, days, page_size=10)
            all_articles.extend(fetched)
        
        # Deduplicar
        seen = set()
        unique = []
        for a in all_articles:
            url = a.get('url', '')
            if url not in seen:
                seen.add(url)
                unique.append(a)
        
        # Filtrar y clasificar por impacto
        classified = []
        for article in unique:
            source = (article.get('source', '') or '').lower()
            title = (article.get('title', '') or '').lower()
            
            # Verificar fuente confiable
            if not any(fs in source for fs in FUENTES_CONFIABLES):
                continue
            
            # Clasificar impacto
            if any(kw in title for kw in MACRO_KEYWORDS_ALTO):
                impacto = 'alto'
            elif any(kw in title for kw in MACRO_KEYWORDS_MEDIO):
                impacto = 'medio'
            else:
                impacto = 'contexto'
            
            classified.append({
                'title':        article['title'],
                'source':       article['source'],
                'url':          article['url'],
                'published_at': article['published_at'],
                'impacto':      impacto,
            })
        
        # Ordenar por impacto
        classified.sort(key=lambda x: (
            {'alto': 0, 'medio': 1, 'contexto': 2}[x['impacto']]
        ))
        
        logger.info("Macro news: %d total, %d unique, %d classified",
                    len(all_articles), len(unique), len(classified))
        
        return classified[:max_results]


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

    def _fetch(self, keyword: str, days: int, page_size: int = 5) -> list:
        """Call NewsAPI and return processed articles."""
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        params = {
            'q':        keyword,
            'from':     from_date,
            'sortBy':   'publishedAt',
            'language': 'en',
            'pageSize': page_size,
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

                url_val = art.get('url', '') or ''
                if not url_val or not url_val.startswith('http'):
                    logger.debug("NewsAPI URL no disponible para '%s': %r", title[:50], url_val)
                processed.append({
                    'title':        title,
                    'source':       art.get('source', {}).get('name', 'Desconocido'),
                    'sentiment':    sentiment,
                    'url':          url_val,
                    'published_at': pub,
                })

            return processed

        except requests.exceptions.Timeout:
            logger.warning("NewsAPI timeout for '%s'", keyword)
            return []
        except Exception as e:
            logger.warning("NewsAPI error for '%s': %s", keyword, e)
            return []
