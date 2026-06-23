"""
pdf_generator.py — Genera el PDF de reporte semanal completo.
Usa fpdf2. Instalar: pip install fpdf2
"""
import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    from fpdf import FPDF, XPos, YPos
    FPDF_OK = True
except ImportError:
    FPDF_OK = False
    FPDF = object  # fallback so class definition below doesn't raise NameError
    XPos = None
    YPos = None
    logger.warning("fpdf2 not installed. Run: pip install fpdf2")


ACTION_COLORS = {
    "COMPRA FUERTE": (0,   128,  0),
    "COMPRA":        (34,  139, 34),
    "MANTENER":      (100, 100, 100),
    "VENTA":         (200,  80,  0),
    "VENTA FUERTE":  (180,   0,  0),
}

INDICATOR_LABELS = {
    "moving_averages": "Medias Moviles (diario)",
    "rsi":             "RSI 14 (semanal)",
    "squeeze":         "Squeeze Momentum (semanal)",
    "adx":             "ADX 14 (semanal)",
    "volume":          "Volumen OBV/CMF (diario)",
    "news":            "Contexto Noticias",
}


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(12, 12, 12)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, f"Analisis Semanal de Inversiones | {datetime.now().strftime('%d/%m/%Y')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(180, 180, 180)
        self.line(12, self.get_y(), 198, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-13)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Pagina {self.page_no()} | Generado automaticamente. No es asesoría financiera.", align="C")


def _safe(text, maxlen=200):
    """Limpia texto para fpdf (ASCII safe)."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("✅", "[OK]").replace("⚠️", "[!]").replace("❌", "[X]")
    text = text.replace("🟢", "[+]").replace("🔴", "[-]").replace("⚡", "[*]")
    text = text.replace("•", "-").replace("→", "->").replace("←", "<-")
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text[:maxlen] if maxlen else text


def generate_report_pdf(
    recommendations: List[Dict[str, Any]],
    portfolio_total_cop: float,
    cop_usd_rate: float,
    output_path: str,
) -> bool:
    """
    Genera el PDF con análisis completo de todos los activos.

    Args:
        recommendations : lista de dicts de scoring.generate_recommendation()
        portfolio_total_cop : valor total del portafolio en COP
        cop_usd_rate : tasa COP/USD
        output_path : ruta .pdf de salida

    Returns:
        True si éxito, False si error
    """
    if not FPDF_OK:
        logger.error("fpdf2 not available. Cannot generate PDF.")
        return False

    try:
        pdf = ReportPDF()
        pdf.add_page()

        # ── PORTADA ──────────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 10, "Reporte Semanal de Inversiones", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 7, datetime.now().strftime("Semana del %d de %B de %Y"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(6)

        # ── RESUMEN PORTAFOLIO ────────────────────────────────────────────────
        pdf.set_fill_color(240, 240, 248)
        pdf.set_draw_color(200, 200, 220)
        pdf.rect(12, pdf.get_y(), 186, 22, "FD")
        pdf.set_xy(16, pdf.get_y() + 3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(30, 30, 80)
        pdf.cell(90, 6, f"Portfolio total: COP ${portfolio_total_cop:,.0f}", new_x=XPos.RIGHT)
        pdf.cell(90, 6, f"Tasa USD/COP: {cop_usd_rate:,.0f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
        pdf.set_x(16)
        pdf.set_font("Helvetica", "", 9)

        # contar señales
        compras   = [r for r in recommendations if "COMPRA" in r.get("action", "")]
        ventas    = [r for r in recommendations if "VENTA"  in r.get("action", "")]
        mantener  = [r for r in recommendations if "MANTENER" in r.get("action", "")]
        pdf.set_text_color(0, 120, 0)
        pdf.cell(60, 5, f"Compras: {len(compras)}", new_x=XPos.RIGHT)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(60, 5, f"Ventas: {len(ventas)}", new_x=XPos.RIGHT)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(60, 5, f"Mantener: {len(mantener)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(8)

        # ── SECCIONES ─────────────────────────────────────────────────────────
        groups = [
            ("COMPRAS", sorted(compras,  key=lambda r: r.get("score",0), reverse=True)),
            ("VENTAS",  sorted(ventas,   key=lambda r: r.get("score",0))),
            ("MANTENER",sorted(mantener, key=lambda r: abs(r.get("score",0)), reverse=True)),
        ]

        for section_title, recs in groups:
            if not recs:
                continue
            _section_header(pdf, section_title)
            for rec in recs:
                _ticker_block(pdf, rec)

        # ── NOTICIAS ──────────────────────────────────────────────────────────
        all_news = []
        for r in recommendations:
            for n in r.get("news", []):
                n["ticker"] = r.get("ticker", "")
                all_news.append(n)

        if all_news:
            _section_header(pdf, "NOTICIAS Y CONTEXTO GEOPOLITICO")
            _news_section(pdf, all_news)

        pdf.output(output_path)
        logger.info("PDF generado: %s", output_path)
        return True

    except Exception as e:
        logger.exception("Error generando PDF: %s", e)
        return False


# ── Helpers de renderizado ────────────────────────────────────────────────────

def _section_header(pdf: "ReportPDF", title: str):
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(30, 30, 80)
    pdf.cell(0, 8, f"  {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.ln(3)


def _ticker_block(pdf: "ReportPDF", rec: dict):
    ticker  = _safe(rec.get("ticker", "-"))
    action  = _safe(rec.get("action", "-"))
    score   = rec.get("score", 0)
    price   = rec.get("price_usd") or 0
    target  = rec.get("target_usd") or 0
    sl      = rec.get("stop_loss_usd") or 0
    conf    = rec.get("confidence", {}).get("score", 0)
    conf_t  = rec.get("confidence", {}).get("total", 6)
    reasons = rec.get("reasons", [])
    comps   = rec.get("score_components", {})

    r, g, b = ACTION_COLORS.get(action, (60, 60, 60))

    # Ticker header bar
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, f"  {ticker}  |  {action}  |  Score: {score:+.1f}/40  |  Confianza: {conf}/{conf_t}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)

    # Price row
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 9)
    price_line = f"Precio: ${price:.2f} USD"
    if target:  price_line += f"   |   Target: ${target:.2f}"
    if sl:      price_line += f"   |   Stop Loss: ${sl:.2f}"
    pdf.cell(0, 5, _safe(price_line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Indicator breakdown table
    if comps:
        _indicator_table(pdf, comps)

    # Reasons
    if reasons:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(60, 60, 60)
        for reason in reasons[:3]:
            pdf.cell(6); pdf.cell(0, 4, _safe(f"- {reason}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)


def _indicator_table(pdf: "ReportPDF", comps: dict):
    col_w = [80, 30, 60]
    headers = ["Indicador", "Pts", "Señal"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 240)
    pdf.set_text_color(30, 30, 30)
    for h, w in zip(headers, col_w):
        pdf.cell(w, 5, h, border="B", align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for key, data in comps.items():
        label  = _safe(INDICATOR_LABELS.get(key, key), 40)
        pts    = data.get("weighted_score", 0) if isinstance(data, dict) else 0
        signal = _safe(data.get("signal", "-") if isinstance(data, dict) else "-", 30)

        color = (0, 110, 0) if pts > 0 else (180, 0, 0) if pts < 0 else (80, 80, 80)
        pdf.set_text_color(*color)
        pdf.cell(col_w[0], 5, f"  {label}")
        pdf.cell(col_w[1], 5, f"{pts:+.1f}", align="C")
        pdf.set_text_color(30, 30, 30)
        pdf.cell(col_w[2], 5, f"  {signal}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(1)


def _news_section(pdf: "ReportPDF", news_list: list):
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(30, 30, 30)

    SENT_COLORS = {
        "positive": (0, 120, 0),
        "negative": (180, 0, 0),
        "neutral":  (80, 80, 80),
    }
    SENT_LABEL = {"positive": "[+]", "negative": "[-]", "neutral": "[ ]"}

    for item in news_list[:40]:
        ticker    = _safe(item.get("ticker", ""))
        title     = _safe(item.get("title", "Sin título"), 120)
        source    = _safe(item.get("source", ""), 30)
        sentiment = item.get("sentiment", "neutral")
        url       = item.get("url", "")

        sl = SENT_LABEL.get(sentiment, "[ ]")
        r, g, b = SENT_COLORS.get(sentiment, (80, 80, 80))

        pdf.set_text_color(r, g, b)
        prefix = f"{sl} [{ticker}] "
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(len(prefix)*2.1, 4, prefix, new_x=XPos.RIGHT)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(30, 30, 30)
        line = title
        if source:
            line += f"  ({source})"
        pdf.multi_cell(0, 4, _safe(line, 160), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        if url:
            pdf.set_font("Helvetica", "I", 7)
            pdf.set_text_color(0, 80, 180)
            pdf.cell(10)
            pdf.cell(0, 3, _safe(url, 120), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(30, 30, 30)
