"""
pdf_generator.py — Reporte PDF usando matplotlib (ya en requirements.txt).
Sin dependencias nuevas. Usa matplotlib.backends.backend_pdf.PdfPages.
"""
import logging
import textwrap
from datetime import datetime
from typing import List, Dict, Any

import matplotlib
matplotlib.use("Agg")   # Sin GUI — funciona en servidores y GitHub Actions
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

logger = logging.getLogger(__name__)

# ── Paleta de colores ─────────────────────────────────────────────────────────
COLORS = {
    "COMPRA FUERTE": "#1a7a1a",
    "COMPRA DEBIL":  "#5cbd5c",
    "MANTENER":      "#888888",
    "VENTA DEBIL":   "#e07030",
    "VENTA":         "#d05000",
    "VENTA FUERTE":  "#b00000",
    "bg_header":     "#1e1e4a",
    "bg_light":      "#f0f0f8",
    "text_dark":     "#1a1a1a",
    "text_gray":     "#555555",
    "green":         "#1a7a1a",
    "red":           "#b00000",
    "neutral":       "#555555",
}

INDICATOR_LABELS = {
    "moving_averages": "Medias Moviles EMA10/55 (diario)",
    "squeeze_adx":     "Squeeze+ADX Trading Latino (semanal)",
    "rsi":             "RSI 14 (semanal)",
    "volume":          "Volumen OBV/CMF (diario)",
    "news":            "Noticias / Contexto",
}


def generate_report_pdf(
    recommendations: List[Dict[str, Any]],
    portfolio_total_cop: float,
    cop_usd_rate: float,
    output_path: str,
) -> bool:
    """
    Genera el PDF completo del reporte semanal usando matplotlib.
    No requiere fpdf2 ni reportlab — matplotlib ya está en requirements.txt.
    """
    try:
        plt.rcParams.update({
            "font.family":    "DejaVu Sans",
            "font.size":      9,
            "figure.facecolor": "white",
            "axes.facecolor":   "white",
        })

        compras  = sorted([r for r in recommendations if "COMPRA" in r.get("action","")],
                          key=lambda x: -x.get("score", 0))
        ventas   = sorted([r for r in recommendations if "VENTA"  in r.get("action","")],
                          key=lambda x:  x.get("score", 0))
        mantener = [r for r in recommendations if r.get("action","") == "MANTENER"]

        with PdfPages(output_path) as pdf:
            # Portada
            pdf.savefig(_make_cover(recommendations, portfolio_total_cop, cop_usd_rate,
                                    len(compras), len(ventas), len(mantener)),
                        bbox_inches="tight")
            plt.close("all")

            # Gráfica distribución por tipo de activo (2 pies: actual vs proyectado)
            pdf.savefig(_make_asset_type_chart(recommendations), bbox_inches="tight")
            plt.close("all")

            # Tabla de composición del portafolio
            pdf.savefig(_make_holdings_table(recommendations, portfolio_total_cop), bbox_inches="tight")
            plt.close("all")

            # Sugerencia de rebalanceo (perfil agresivo)
            pdf.savefig(_make_rebalancing_page(recommendations, portfolio_total_cop), bbox_inches="tight")
            plt.close("all")

            # Gráfica distribución por señal
            pdf.savefig(_make_portfolio_chart(recommendations), bbox_inches="tight")
            plt.close("all")

            # Sección COMPRAS
            if compras:
                pdf.savefig(_make_section_header("COMPRAS", compras, COLORS["COMPRA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for rec in compras:
                    pdf.savefig(_make_ticker_page(rec), bbox_inches="tight")
                    plt.close("all")

            # Sección VENTAS
            if ventas:
                pdf.savefig(_make_section_header("VENTAS", ventas, COLORS["VENTA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for rec in ventas:
                    pdf.savefig(_make_ticker_page(rec), bbox_inches="tight")
                    plt.close("all")

            # MANTENER (resumen compacto)
            if mantener:
                pdf.savefig(_make_mantener_page(mantener), bbox_inches="tight")
                plt.close("all")

            # Metadata
            d = pdf.infodict()
            d["Title"]   = "Reporte Semanal de Inversiones"
            d["Subject"] = f"Análisis {datetime.now().strftime('%d/%m/%Y')}"

        logger.info("PDF generado: %s", output_path)
        return True

    except Exception as e:
        logger.exception("Error generando PDF: %s", e)
        return False


# ── Páginas ───────────────────────────────────────────────────────────────────

def _make_asset_type_chart(recs: list):
    """
    Página: Distribución por tipo de activo (asset_type).
      - Izquierda: pie actual (COP por asset_type)
      - Derecha:   pie proyectado después de ejecutar señales
        VENTA FUERTE → retiene 0%
        VENTA DEBIL  → retiene 50%
        COMPRA FUERTE → crece +25%
        COMPRA DEBIL  → crece +10%
        MANTENER      → sin cambio
    """
    RETAIN = {
        "COMPRA FUERTE": 1.25,
        "COMPRA DEBIL":  1.10,
        "MANTENER":      1.00,
        "VENTA DEBIL":   0.50,
        "VENTA FUERTE":  0.00,
    }
    ASSET_COLORS = {
        "Crecimiento":        "#2196F3",
        "Defensiva":          "#4CAF50",
        "Materias Primas":    "#FF9800",
        "Sectorial":          "#9C27B0",
        "Otro":               "#9E9E9E",
    }

    # Agrupar valores actuales y proyectados por asset_type
    current_by_type:   dict = {}
    projected_by_type: dict = {}

    for r in recs:
        atype  = r.get("asset_type", "Otro") or "Otro"
        action = r.get("action", "MANTENER")
        val    = float(r.get("current_value_cop", 0) or 0)
        factor = RETAIN.get(action, 1.0)

        current_by_type[atype]   = current_by_type.get(atype, 0)   + val
        projected_by_type[atype] = projected_by_type.get(atype, 0) + val * factor

    all_types  = sorted(set(list(current_by_type) + list(projected_by_type)))
    cur_vals   = [current_by_type.get(t, 0)   for t in all_types]
    proj_vals  = [projected_by_type.get(t, 0) for t in all_types]
    pie_colors = [ASSET_COLORS.get(t, "#9E9E9E") for t in all_types]

    total_cur  = sum(cur_vals)  or 1
    total_proj = sum(proj_vals) or 1

    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.6, "Distribución por Tipo de Activo",
              ha="center", va="center", fontsize=14, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18,
              "Izquierda: portafolio actual  |  Derecha: proyección después de ejecutar señales",
              ha="center", va="center", fontsize=8.5, color="#aaaadd")

    # ── Pie ACTUAL ────────────────────────────────────────────────────────────
    ax_cur = fig.add_axes([0.02, 0.55, 0.46, 0.35])
    w1, _, at1 = ax_cur.pie(
        cur_vals, colors=pie_colors,
        autopct=lambda p: f"{p:.1f}%" if p > 4 else "",
        startangle=90, pctdistance=0.72,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for at in at1:
        at.set_fontsize(8); at.set_color("white"); at.set_fontweight("bold")
    ax_cur.set_title(f"Actual\nCOP ${total_cur:,.0f}", fontsize=10,
                     fontweight="bold", color=COLORS["text_dark"], pad=6)
    ax_cur.legend(w1, all_types, loc="lower center",
                  bbox_to_anchor=(0.5, -0.14), fontsize=8, frameon=False, ncol=2)

    # ── Pie PROYECTADO ────────────────────────────────────────────────────────
    ax_prj = fig.add_axes([0.52, 0.55, 0.46, 0.35])
    w2, _, at2 = ax_prj.pie(
        proj_vals, colors=pie_colors,
        autopct=lambda p: f"{p:.1f}%" if p > 4 else "",
        startangle=90, pctdistance=0.72,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for at in at2:
        at.set_fontsize(8); at.set_color("white"); at.set_fontweight("bold")
    delta_cop = total_proj - total_cur
    delta_str = f"+COP ${delta_cop:,.0f}" if delta_cop >= 0 else f"-COP ${abs(delta_cop):,.0f}"
    ax_prj.set_title(f"Proyectado ({delta_str})\nCOP ${total_proj:,.0f}", fontsize=10,
                     fontweight="bold", color=COLORS["text_dark"], pad=6)
    ax_prj.legend(w2, all_types, loc="lower center",
                  bbox_to_anchor=(0.5, -0.14), fontsize=8, frameon=False, ncol=2)

    # ── Tabla de impacto por activo ───────────────────────────────────────────
    ax_t = fig.add_axes([0.02, 0.06, 0.96, 0.46])
    ax_t.axis("off")
    ax_t.text(0, 0.99, "Impacto por activo (solo señales con efecto):",
              fontsize=10, fontweight="bold", color=COLORS["text_dark"],
              va="top", transform=ax_t.transAxes)

    impact_recs = [r for r in recs if r.get("action","MANTENER") != "MANTENER"]
    impact_recs.sort(key=lambda x: -abs(x.get("score", 0)))

    tbl_data = []
    tbl_row_colors = []
    for r in impact_recs[:18]:
        action  = r.get("action", "")
        val     = float(r.get("current_value_cop", 0) or 0)
        factor  = RETAIN.get(action, 1.0)
        proj    = val * factor
        delta   = proj - val
        delta_s = f"+{delta:,.0f}" if delta >= 0 else f"{delta:,.0f}"
        tbl_data.append([
            r.get("ticker", ""),
            r.get("asset_type", ""),
            action,
            f"{r.get('score', 0):+.1f}",
            f"{val:,.0f}",
            f"{proj:,.0f}",
            delta_s,
        ])
        c = COLORS.get(action, COLORS["MANTENER"])
        tbl_row_colors.append([c, "#f5f5f5", c, "#f5f5f5", "#f5f5f5", "#f5f5f5", "#f5f5f5"])

    if tbl_data:
        tbl = ax_t.table(
            cellText=tbl_data,
            colLabels=["Ticker", "Tipo", "Señal", "Score", "Actual COP", "Proy. COP", "Delta"],
            loc="upper center", bbox=[0, 0, 1, 0.95],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(7.5)
        tbl.auto_set_column_width(list(range(7)))
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#2d3a5a")
                cell.set_text_props(fontweight="bold", color="white")
            elif r <= len(tbl_row_colors):
                cell.set_facecolor(tbl_row_colors[r-1][c])
                if c in (0, 2):
                    cell.set_text_props(color="white", fontweight="bold")

    # ── Nota de proyección ────────────────────────────────────────────────────
    ax_n = fig.add_axes([0.02, 0.02, 0.96, 0.04])
    ax_n.axis("off")
    ax_n.text(0.5, 0.5,
              "Proyección asume: VENTA FUERTE -100% | VENTA DEBIL -50% | "
              "COMPRA FUERTE +25% | COMPRA DEBIL +10% | MANTENER sin cambio",
              ha="center", va="center", fontsize=7, color="#888888", style="italic")
    return fig


def _make_holdings_table(recs: list, total_cop: float):
    """
    Tabla de posiciones propias: ticker, tipo, valor COP y % del portafolio.
    Solo activos con posición (value > 0), ordenados de mayor a menor peso.
    """
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.6, "Composición del Portafolio",
              ha="center", va="center", fontsize=14, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18, f"COP ${total_cop:,.0f} en activos propios",
              ha="center", va="center", fontsize=9, color="#aaaadd")

    owned = [r for r in recs if (r.get("current_value_cop") or 0) > 0]
    owned.sort(key=lambda x: -(x.get("current_value_cop") or 0))

    # ── Tabla portafolio propio ───────────────────────────────────────────────
    ax_p = fig.add_axes([0.01, 0.04, 0.98, 0.87])
    ax_p.axis("off")
    ax_p.text(0, 0.99, "Posiciones actuales (ordenadas por peso):", fontsize=10,
              fontweight="bold", color=COLORS["text_dark"], va="top", transform=ax_p.transAxes)

    tbl_data   = []
    tbl_colors = []
    for r in owned:
        val  = float(r.get("current_value_cop", 0) or 0)
        pct  = val / total_cop * 100 if total_cop else 0
        act  = r.get("action", "—")
        bar  = "█" * int(pct / 2) if pct >= 1 else "▏"
        tbl_data.append([
            r.get("ticker", ""),
            r.get("asset_type", ""),
            r.get("asset_subtype", ""),
            f"COP {val:,.0f}",
            f"{pct:.2f}%",
            bar,
        ])
        rc = COLORS.get(act, "#f5f5f5")
        tbl_colors.append([rc, "#f0f0f0", "#f0f0f0", "#f5f5f5", "#f5f5f5", "#e8f0ff"])

    if tbl_data:
        tbl = ax_p.table(
            cellText=tbl_data,
            colLabels=["Ticker", "Tipo", "Subtipo", "Valor COP", "% Port.", "Peso visual"],
            loc="upper center", bbox=[0, 0, 1, 0.97],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width(list(range(6)))
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#2d3a5a")
                cell.set_text_props(fontweight="bold", color="white")
            elif r <= len(tbl_colors):
                cell.set_facecolor(tbl_colors[r-1][c])
                if c == 0:
                    cell.set_text_props(fontweight="bold", color="white")
                if c == 5:
                    cell.set_text_props(color="#3355aa", fontfamily="monospace")

    # ── Footer ────────────────────────────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.03])
    ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              "Color de ticker = señal actual del analisis tecnico",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


# ── Perfil agresivo: targets y sugerencias ────────────────────────────────────
_AGRESIVO_TARGETS = {
    "Crecimiento":    0.70,
    "Defensiva":      0.15,
    "Materias Primas": 0.08,
    "Sectorial":      0.07,
}

_REBAL_SUGGESTIONS = [
    # (ticker, accion, razon, cop_delta_label)
    ("XLV",   "REDUCIR",  "Defensiva sobrePonderada (19% actual vs ~6% objetivo). Salud tiene presion regulatoria.",          "-~COP 4.4M"),
    ("BACCO", "VENDER",   "Banco individual con alta correlacion a IUFSCO. Elimina concentracion en financiero.",             "-~COP 974K"),
    ("SOXX",  "AUMENTAR", "Semiconductores: ciclo AI en expansion. Aumentar exposicion a growth de alta conviccion.",         "+~COP 2.5M"),
    ("QQQ",   "AUMENTAR", "Nasdaq 100: mejor vehiculo para crecimiento tech puro. Complementa IUITCO y CSPXCO.",              "+~COP 1.5M"),
    ("URA",   "AUMENTAR", "Nuclear: energia limpia con vientos favorables (politica global). Refuerza Sectorial.",            "+~COP 900K"),
    ("ETH",   "INICIAR",  "Crypto exposicion moderada (~1%). Alta volatilidad pero retorno asimetrico para perfil agresivo.", "+~COP 330K"),
]


def _make_rebalancing_page(recs: list, total_cop: float):
    """
    Sugerencia de rebalanceo para perfil agresivo (arriesgado):
      - Grafica barras: asignacion actual vs objetivo
      - Tabla: acciones concretas con razon y COP estimado
    """
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#2d1a5a", ec="none"))
    ax_h.text(0.5, 0.62, "Sugerencia de Rebalanceo - Perfil Agresivo",
              ha="center", va="center", fontsize=13, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18,
              "Objetivo: maximizar crecimiento con exposicion controlada a defensivos y materias primas",
              ha="center", va="center", fontsize=8, color="#ccaaff")

    # ── Calcular asignacion actual por tipo ───────────────────────────────────
    owned = [r for r in recs if (r.get("current_value_cop") or 0) > 0]
    type_totals: dict = {}
    for r in owned:
        atype = r.get("asset_type", "Otro")
        # Normalizar Blockchain → Crecimiento para el rebalanceo
        if atype == "Blockchain":
            atype = "Crecimiento"
        val = float(r.get("current_value_cop", 0) or 0)
        type_totals[atype] = type_totals.get(atype, 0) + val

    # Consolidar tipos menores en su categoría más cercana
    for extra_type in list(type_totals.keys()):
        if extra_type not in _AGRESIVO_TARGETS:
            # Poner en Sectorial si no clasificado
            type_totals["Sectorial"] = type_totals.get("Sectorial", 0) + type_totals.pop(extra_type)

    total = sum(type_totals.values()) or total_cop or 1

    categories = list(_AGRESIVO_TARGETS.keys())
    actual_pcts  = [type_totals.get(c, 0) / total * 100 for c in categories]
    target_pcts  = [_AGRESIVO_TARGETS[c] * 100 for c in categories]

    # ── Grafica barras ───────────────────────────────────────────────────────
    ax_b = fig.add_axes([0.08, 0.62, 0.88, 0.28])
    x = np.arange(len(categories))
    w = 0.35
    bars_act = ax_b.bar(x - w/2, actual_pcts, w, label="Actual",
                        color=["#3366cc","#cc3333","#cc8833","#228833"], alpha=0.85, zorder=3)
    bars_tgt = ax_b.bar(x + w/2, target_pcts, w, label="Objetivo agresivo",
                        color=["#99bbff","#ffaaaa","#ffcc88","#88dd88"], alpha=0.85,
                        edgecolor="#555555", linewidth=0.8, zorder=3)

    ax_b.set_xticks(x)
    ax_b.set_xticklabels(categories, fontsize=9)
    ax_b.set_ylabel("% del portafolio", fontsize=8)
    ax_b.set_title("Asignacion Actual vs Objetivo (Perfil Agresivo)", fontsize=10, fontweight="bold", pad=6)
    ax_b.legend(fontsize=8, loc="upper right")
    ax_b.set_ylim(0, max(max(actual_pcts), max(target_pcts)) * 1.18)
    ax_b.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_b.set_axisbelow(True)
    ax_b.tick_params(axis="both", labelsize=8)

    # Etiquetas sobre las barras
    for bar, pct in zip(bars_act, actual_pcts):
        ax_b.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                  f"{pct:.1f}%", ha="center", va="bottom", fontsize=7, color="#222222")
    for bar, pct in zip(bars_tgt, target_pcts):
        ax_b.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                  f"{pct:.0f}%", ha="center", va="bottom", fontsize=7, color="#444444")

    # ── Lookup señales tecnicas del analisis semanal ─────────────────────────
    signals = {}
    for r in recs:
        tk     = r.get("ticker", "")
        action = r.get("action", "")
        score  = float(r.get("score", 0) or 0)
        sq     = r.get("squeeze_state", "")
        adx    = float(r.get("adx_value", 0) or 0)
        signals[tk] = {"action": action, "score": score, "squeeze": sq, "adx": adx}

    def _entry_assessment(ticker, accion_rebal):
        """
        Cruza la sugerencia de rebalanceo con la señal tecnica semanal.
        Devuelve (etiqueta, color_fondo).
        """
        sig = signals.get(ticker)
        if not sig:
            return "Sin datos", "#eeeeee"
        action = sig["action"]
        score  = sig["score"]
        sq     = sig["squeeze"]
        is_buy_rebal  = accion_rebal in ("AUMENTAR", "INICIAR")
        is_sell_rebal = accion_rebal in ("REDUCIR", "VENDER")

        if is_buy_rebal:
            if "COMPRA FUERTE" in action:
                return "ENTRADA IDEAL", "#b8f0b8"      # verde fuerte
            elif "COMPRA" in action:
                return "Entrada favorable", "#d8f4d8"  # verde suave
            elif "MANTENER" in action:
                if sq == "compressed":
                    return "Esperar release", "#fff3cc"  # amarillo — squeeze comprimido, esperar
                return "Sin señal clara", "#f0f0f0"
            else:  # VENTA
                return "Señal contraria", "#fdd8c8"    # naranja — tecnico dice vender
        elif is_sell_rebal:
            if "VENTA FUERTE" in action:
                return "MOMENTO OPORTUNO", "#ffa8a8"   # rojo fuerte
            elif "VENTA" in action:
                return "Buen momento", "#ffc8b0"       # naranja suave
            elif "MANTENER" in action:
                return "Sin urgencia", "#f0f0f0"
            else:  # COMPRA
                return "Señal contraria", "#d8f4d8"    # verde — tecnico dice comprar, cuidado vender
        return "—", "#f5f5f5"

    # ── Tabla de sugerencias ──────────────────────────────────────────────────
    ax_t = fig.add_axes([0.01, 0.07, 0.98, 0.52])
    ax_t.axis("off")
    ax_t.text(0, 0.99, "Acciones sugeridas (con señal tecnica semanal):",
              fontsize=10, fontweight="bold", color=COLORS["text_dark"],
              va="top", transform=ax_t.transAxes)

    sug_data   = []
    sug_colors = []
    for ticker, accion, razon, cop_delta in _REBAL_SUGGESTIONS:
        sig         = signals.get(ticker, {})
        tech_action = sig.get("action", "—")
        tech_score  = sig.get("score", 0)
        tech_str    = f"{tech_action} ({tech_score:+.0f})" if tech_action != "—" else "Sin datos"
        entry_lbl, entry_bg = _entry_assessment(ticker, accion)
        wrapped = textwrap.fill(razon, width=48)
        sug_data.append([ticker, accion, wrapped, tech_str, entry_lbl, cop_delta])

        if "VENDER" in accion or "REDUCIR" in accion:
            base_ticker_col = COLORS["VENTA FUERTE"]
            base_row_col    = "#fff0ec"
        else:
            base_ticker_col = COLORS["COMPRA FUERTE"]
            base_row_col    = "#f0fff0"

        sug_colors.append([
            base_ticker_col,  # ticker col
            base_row_col,     # accion col
            "#fafafa",        # razon col
            "#f5f5f5",        # señal tecnica col
            entry_bg,         # momento col
            base_row_col,     # COP col
        ])

    tbl = ax_t.table(
        cellText=sug_data,
        colLabels=["Ticker", "Accion", "Razon", "Señal tecnica", "Momento entrada", "COP est."],
        loc="upper center", bbox=[0, 0, 1, 0.94],
    )
    tbl.auto_set_font_size(False); tbl.set_fontsize(7)
    tbl.auto_set_column_width([0, 1, 2, 3, 4, 5])

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#cccccc")
        if r == 0:
            cell.set_facecolor("#2d1a5a")
            cell.set_text_props(fontweight="bold", color="white", fontsize=7.5)
        elif r <= len(sug_colors):
            cell.set_facecolor(sug_colors[r-1][c])
            if c == 0:
                cell.set_text_props(fontweight="bold", color="white")
            if c == 4:
                cell.set_text_props(fontweight="bold", fontsize=6.5)
        cell.set_height(cell.get_height() * 1.5)

    # ── Leyenda de momento ─────────────────────────────────────────────────────
    ax_l = fig.add_axes([0.02, 0.01, 0.96, 0.055])
    ax_l.axis("off")
    leyenda = [
        ("ENTRADA IDEAL / MOMENTO OPORTUNO", "#b8f0b8"),
        ("Entrada favorable / Buen momento", "#d8f4d8"),
        ("Esperar release / Sin urgencia",   "#fff3cc"),
        ("Señal contraria — revisar",        "#fdd8c8"),
    ]
    for i, (label, color) in enumerate(leyenda):
        x0 = i / len(leyenda)
        ax_l.add_patch(mpatches.FancyBboxPatch((x0 + 0.005, 0.1), 0.23, 0.8,
                       boxstyle="round,pad=0.02", fc=color, ec="#aaaaaa", linewidth=0.6))
        ax_l.text(x0 + 0.12, 0.5, label, ha="center", va="center",
                  fontsize=5.8, color="#333333")

    return fig


def _make_portfolio_chart(recs: list):
    """
    Página 2: Vista del portafolio por tipo de acción.
      - Izquierda: donut chart (número de activos)
      - Derecha:   barras horizontales (% del portafolio en COP)
      - Abajo:     tabla de top activos por score absoluto
    """
    ORDER  = ["COMPRA FUERTE", "COMPRA DEBIL", "MANTENER", "VENTA DEBIL", "VENTA FUERTE"]
    CLABEL = {"COMPRA FUERTE": "Compra\nFuerte", "COMPRA DEBIL": "Compra\nDebil",
              "MANTENER": "Mantener", "VENTA DEBIL": "Venta\nDebil", "VENTA FUERTE": "Venta\nFuerte"}

    # Agrupar
    groups: dict[str, list] = {k: [] for k in ORDER}
    for r in recs:
        a = r.get("action", "MANTENER")
        key = a if a in groups else "MANTENER"
        groups[key].append(r)

    labels  = [k for k in ORDER if groups[k]]
    counts  = [len(groups[k]) for k in labels]
    colors  = [COLORS[k] for k in labels]
    total_cop_val = sum(r.get("current_value_cop", 0) or 0 for r in recs) or 1
    pcts    = [
        sum((r.get("current_value_cop", 0) or 0) for r in groups[k]) / total_cop_val * 100
        for k in labels
    ]

    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.55, "Distribución del Portafolio por Señal",
              ha="center", va="center", fontsize=14, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18, f"{len(recs)} activos analizados — {datetime.now().strftime('%d/%m/%Y')}",
              ha="center", va="center", fontsize=9, color="#aaaadd")

    # ── Donut chart (izquierda) ────────────────────────────────────────────────
    ax_d = fig.add_axes([0.02, 0.58, 0.44, 0.33])
    wedges, texts, autotexts = ax_d.pie(
        counts, labels=None, colors=colors,
        autopct=lambda p: f"{p:.0f}%" if p > 5 else "",
        startangle=90, pctdistance=0.75,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 1.5},
    )
    for at in autotexts:
        at.set_fontsize(9); at.set_fontweight("bold"); at.set_color("white")
    ax_d.set_title("N.° de activos", fontsize=10, fontweight="bold",
                   color=COLORS["text_dark"], pad=8)

    # Leyenda
    ax_d.legend(
        wedges,
        [f"{CLABEL[k]}  ({len(groups[k])})" for k in labels],
        loc="lower center", bbox_to_anchor=(0.5, -0.18),
        fontsize=8, ncol=2, frameon=False,
    )

    # ── Barras horizontales (derecha) ──────────────────────────────────────────
    ax_b = fig.add_axes([0.52, 0.60, 0.44, 0.28])
    ax_b.set_xlim(0, max(pcts) * 1.15 if pcts else 100)
    ax_b.set_ylim(-0.5, len(labels) - 0.5)
    ax_b.set_yticks(range(len(labels)))
    ax_b.set_yticklabels([CLABEL[k] for k in labels], fontsize=9)
    ax_b.set_xlabel("% del portafolio (COP)", fontsize=8)
    ax_b.set_title("Exposición en COP", fontsize=10, fontweight="bold",
                   color=COLORS["text_dark"])
    ax_b.spines[["top", "right"]].set_visible(False)
    ax_b.tick_params(axis="x", labelsize=8)

    for i, (pct, color) in enumerate(zip(pcts, colors)):
        ax_b.barh(i, pct, color=color, alpha=0.85, height=0.6)
        ax_b.text(pct + 0.5, i, f"{pct:.1f}%", va="center", fontsize=8,
                  color=COLORS["text_dark"], fontweight="bold")

    # ── Tabla: top activos por score absoluto ──────────────────────────────────
    ax_t = fig.add_axes([0.02, 0.08, 0.96, 0.46])
    ax_t.axis("off")
    ax_t.text(0, 0.99, "Ranking de activos por señal (score absoluto):",
              fontsize=10, fontweight="bold", color=COLORS["text_dark"],
              va="top", transform=ax_t.transAxes)

    sorted_recs = sorted(recs, key=lambda x: -abs(x.get("score", 0)))[:20]

    tbl_data   = []
    tbl_colors = []
    for r in sorted_recs:
        act   = r.get("action", "")
        score = r.get("score", 0)
        price = r.get("price_usd", 0) or 0
        val   = r.get("current_value_cop", 0) or 0
        pct_p = r.get("pct_portfolio", "") or ""
        tbl_data.append([
            r.get("ticker", ""),
            act,
            f"{score:+.1f}",
            f"${price:.2f}",
            f"COP {val:,.0f}" if val else "—",
            str(pct_p),
        ])
        rc = COLORS.get(act, COLORS["MANTENER"])
        tbl_colors.append([rc, rc, rc, "#f5f5f5", "#f5f5f5", "#f5f5f5"])

    if tbl_data:
        tbl = ax_t.table(
            cellText=tbl_data,
            colLabels=["Ticker", "Acción", "Score", "Precio USD", "Valor COP", "% Port."],
            loc="upper center", bbox=[0, 0, 1, 0.95],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width([0, 1, 2, 3, 4, 5])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#2d3a5a")
                cell.set_text_props(fontweight="bold", color="white")
            elif r <= len(tbl_colors):
                cell.set_facecolor(tbl_colors[r - 1][c])
                if c <= 2:
                    cell.set_text_props(color="white", fontweight="bold")

    # ── Footer ────────────────────────────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.04])
    ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              "No constituye asesoría financiera. Solo para referencia personal.",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


def _make_cover(recs, total_cop, cop_rate, n_comp, n_vent, n_mant):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    # Header band
    ax.add_patch(mpatches.FancyBboxPatch((0, 0.82), 1, 0.18,
                 boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax.text(0.5, 0.93, "Reporte Semanal de Inversiones",
            ha="center", va="center", fontsize=20, fontweight="bold",
            color="white", transform=ax.transAxes)
    ax.text(0.5, 0.86, datetime.now().strftime("%A %d de %B de %Y"),
            ha="center", va="center", fontsize=12, color="#aaaadd",
            transform=ax.transAxes)

    # Portfolio summary box
    ax.add_patch(mpatches.FancyBboxPatch((0.05, 0.65), 0.90, 0.14,
                 boxstyle="round,pad=0.01", fc=COLORS["bg_light"], ec="#cccccc"))
    ax.text(0.5, 0.75, f"Portfolio Total:  COP ${total_cop:,.0f}",
            ha="center", va="center", fontsize=13, fontweight="bold",
            color=COLORS["text_dark"], transform=ax.transAxes)
    ax.text(0.5, 0.70, f"Tasa USD/COP: {cop_rate:,.0f}  |  Activos analizados: {len(recs)}",
            ha="center", va="center", fontsize=10, color=COLORS["text_gray"],
            transform=ax.transAxes)

    # Signal summary
    for i, (label, n, color) in enumerate([
        ("COMPRAS", n_comp, COLORS["COMPRA FUERTE"]),
        ("VENTAS",  n_vent, COLORS["VENTA FUERTE"]),
        ("MANTENER",n_mant, COLORS["MANTENER"]),
    ]):
        x = 0.18 + i * 0.32
        ax.add_patch(mpatches.FancyBboxPatch((x - 0.12, 0.50), 0.24, 0.12,
                     boxstyle="round,pad=0.01", fc=color, ec="none", alpha=0.9))
        ax.text(x, 0.59, str(n),    ha="center", va="center",
                fontsize=22, fontweight="bold", color="white", transform=ax.transAxes)
        ax.text(x, 0.52, label, ha="center", va="center",
                fontsize=9, color="white", transform=ax.transAxes)

    # Methodology note
    note = (
        "Metodología: EMA 10/55 diario · Squeeze Momentum LazyBear semanal (Trading Latino)\n"
        "ADX 14 semanal · RSI 14 semanal · OBV/VWAP/CMF diario · Noticias NewsAPI\n\n"
        "Señal de COMPRA: Squeeze liberado + histograma verde subiendo + ADX > 25 + DI+ > DI-\n"
        "Señal de VENTA:  Squeeze liberado + histograma rojo bajando  + ADX > 25 + DI- > DI+"
    )
    ax.text(0.5, 0.37, note, ha="center", va="center", fontsize=8.5,
            color=COLORS["text_gray"], transform=ax.transAxes,
            linespacing=1.6, bbox=dict(fc="#f8f8ff", ec="#ddddee", pad=8))

    ax.text(0.5, 0.05,
            "Este reporte es generado automáticamente. No constituye asesoría financiera.\n"
            "Siempre realiza tu propio análisis antes de tomar decisiones de inversión.",
            ha="center", va="center", fontsize=7.5, color="#999999",
            transform=ax.transAxes, linespacing=1.5)
    return fig


def _make_section_header(title, recs, color):
    fig, ax = plt.subplots(figsize=(8.5, 4))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.55), 1, 0.45,
                 boxstyle="square,pad=0", fc=color, ec="none"))
    ax.text(0.5, 0.78, f"SECCIÓN: {title}", ha="center", va="center",
            fontsize=22, fontweight="bold", color="white", transform=ax.transAxes)
    ax.text(0.5, 0.62, f"{len(recs)} activo(s) con señal",
            ha="center", va="center", fontsize=12, color="white", alpha=0.85,
            transform=ax.transAxes)

    # Mini tabla de resumen
    col_labels = ["Ticker", "Score", "Precio USD", "Target", "Stop Loss"]
    rows = []
    for r in recs[:10]:
        rows.append([
            r.get("ticker", ""),
            f"{r.get('score', 0):+.1f}",
            f"${r.get('price_usd', 0):.2f}",
            f"${r.get('target_usd') or 0:.2f}" if r.get("target_usd") else "—",
            f"${r.get('stop_loss_usd') or 0:.2f}" if r.get("stop_loss_usd") else "—",
        ])

    if rows:
        tbl = ax.table(cellText=rows, colLabels=col_labels,
                       loc="center", bbox=[0.02, -0.05, 0.96, 0.48])
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        for (r, c), cell in tbl.get_celld().items():
            if r == 0:
                cell.set_facecolor("#eeeeee"); cell.set_text_props(fontweight="bold")
            else:
                cell.set_facecolor("white" if r % 2 == 0 else "#fafafa")
            cell.set_edgecolor("#dddddd")

    return fig


def _make_ticker_page(rec: dict):
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    ticker  = rec.get("ticker", "—")
    action  = rec.get("action", "—")
    score   = rec.get("score", 0)
    price   = rec.get("price_usd", 0)
    target  = rec.get("target_usd")
    sl      = rec.get("stop_loss_usd")
    conf    = rec.get("confidence", {})
    comps   = rec.get("score_components", {})
    reasons = rec.get("reasons", [])
    color   = COLORS.get(action, COLORS["MANTENER"])

    # Trading Latino extras
    sq_state   = rec.get("squeeze_state", "")
    sqzm_color = rec.get("sqzm_color", "")
    sqzm_valley= rec.get("sqzm_valley", False)
    sqzm_peak  = rec.get("sqzm_peak",   False)
    adx_v      = rec.get("adx_value", 0)
    rsi_v      = rec.get("rsi_value", 0)

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.91, 1, 0.09])
    ax_h.set_xlim(0, 1); ax_h.set_ylim(0, 1); ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=color, ec="none"))
    ax_h.text(0.03, 0.65, ticker, fontsize=20, fontweight="bold",
              color="white", va="center")
    ax_h.text(0.03, 0.22, action, fontsize=11, color="white", alpha=0.9, va="center")
    ax_h.text(0.97, 0.65, f"Score: {score:+.1f}/40", fontsize=14,
              fontweight="bold", color="white", va="center", ha="right")
    ax_h.text(0.97, 0.22,
              f"Confianza: {conf.get('score',0)}/{conf.get('total',5)}",
              fontsize=9, color="white", alpha=0.85, va="center", ha="right")

    # ── Precios ───────────────────────────────────────────────────────────────
    ax_p = fig.add_axes([0, 0.83, 1, 0.08])
    ax_p.set_xlim(0, 1); ax_p.set_ylim(0, 1); ax_p.axis("off")
    ax_p.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_light"], ec="#cccccc",
                   linewidth=0.5))
    price_str = f"Precio: ${price:.2f} USD"
    if target: price_str += f"   |   Target: ${target:.2f}"
    if sl:     price_str += f"   |   Stop Loss: ${sl:.2f}"
    ax_p.text(0.5, 0.6, price_str, ha="center", va="center",
              fontsize=10.5, fontweight="bold", color=COLORS["text_dark"])

    # ── Bloque Trading Latino ─────────────────────────────────────────────────
    ax_tl = fig.add_axes([0.02, 0.71, 0.96, 0.11])
    ax_tl.set_xlim(0, 1); ax_tl.set_ylim(0, 1); ax_tl.a
    ax_tl.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                    boxstyle="round,pad=0.02", fc="#fffbe6", ec="#e0c040", linewidth=0.8))
    ax_tl.text(0.5, 0.85, "Estrategia Trading Latino (semanal)",
               ha="center", va="center", fontsize=9.5, fontweight="bold",
               color="#7a6000")

    sq_label  = {"compressed": "COMPRIMIDO (acumulando presion)",
                 "released":   "LIBERADO (energia en movimiento)",
                 "expanding":  "EXPANDIENDO"}.get(sq_state, sq_state.upper())
    hist_label = {
        "green_strong": "VERDE SUBIENDO  - momentum alcista creciente",
        "green_weak":   "VERDE DEBILITANDO - momentum alcista perdiendo fuerza",
        "red_strong":   "ROJO BAJANDO  - momentum bajista creciente",
        "red_weak":     "ROJO DEBILITANDO  - momentum bajista perdiendo fuerza",
    }.get(sqzm_color, sqzm_color)

    entry_tag = ""
    if sqzm_valley: entry_tag = "  >>> ENTRADA VALLE (señal optima de compra)"
    if sqzm_peak:   entry_tag = "  >>> ENTRADA PICO  (señal optima de venta)"

    tl_line1 = f"Squeeze: {sq_label}"
    tl_line2 = f"Histograma: {hist_label}{entry_tag}"
    tl_line3 = f"ADX: {adx_v:.1f} {'(tendencia fuerte)' if adx_v >= 25 else '(tendencia debil)'}   |   RSI semanal: {rsi_v:.1f}"

    for y, txt in [(0.62, tl_line1), (0.40, tl_line2), (0.16, tl_line3)]:
        ax_tl.text(0.02, y, txt, va="center", fontsize=8.5, color="#5a4000")

    # -- Tabla de indicadores -------------------------------------------------
    ax_t = fig.add_axes([0.02, 0.38, 0.96, 0.32])
    ax_t.set_xlim(0, 1); ax_t.set_ylim(0, 1); ax_t.axis("off")
    ax_t.text(0, 0.97, "Desglose de indicadores:", fontsize=9.5,
              fontweight="bold", color=COLORS["text_dark"], va="top")

    rows, row_colors = [], []
    for key, comp in comps.items():
        label   = INDICATOR_LABELS.get(key, key)
        pts     = float(comp.get("weighted_score", 0) or 0)
        signal  = str(comp.get("signal", "") or "")
        details = str(comp.get("details", "") or "")
        rows.append([label, f"{pts:+.1f}", signal,
                     textwrap.shorten(details, width=55, placeholder="...")])
        rc = "#e8f5e8" if pts > 0 else "#fde8e8" if pts < 0 else "#f5f5f5"
        row_colors.append([rc, rc, rc, rc])

    if rows:
        tbl = ax_t.table(
            cellText=rows,
            colLabels=["Indicador", "Pts", "Señal", "Detalle"],
            loc="center", bbox=[0, 0, 1, 0.90],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width([0, 1, 2, 3])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#ddddee")
                cell.set_text_props(fontweight="bold")
            elif r <= len(row_colors):
                cell.set_facecolor(row_colors[r - 1][c])

    # -- Razones --------------------------------------------------------------
    if reasons:
        ax_r = fig.add_axes([0.02, 0.18, 0.96, 0.19])
        ax_r.set_xlim(0, 1); ax_r.set_ylim(0, 1); ax_r.axis("off")
        ax_r.text(0, 0.97, "Resumen de señales:", fontsize=9.5,
                  fontweight="bold", color=COLORS["text_dark"], va="top")
        for i, reason in enumerate(reasons[:5]):
            col = COLORS["green"] if reason.startswith("[+]") else \
                  COLORS["red"]   if reason.startswith("[-]") else COLORS["neutral"]
            ax_r.text(0.02, 0.80 - i * 0.18, reason, fontsize=8.5,
                      color=col, va="center")

    # -- Footer ---------------------------------------------------------------
    ax_f = fig.add_axes([0, 0, 1, 0.05])
    ax_f.set_xlim(0, 1); ax_f.set_ylim(0, 1); ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              f"Generado {datetime.now().strftime('%d/%m/%Y %H:%M')} | "
              "No constituye asesoria financiera",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


def _make_mantener_page(mantener: list):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.92), 1, 0.08,
                 boxstyle="square,pad=0", fc=COLORS["MANTENER"], ec="none"))
    ax.text(0.5, 0.96, f"MANTENER - {len(mantener)} activos",
            ha="center", va="center", fontsize=16, fontweight="bold",
            color="white", transform=ax.transAxes)

    rows = []
    for r in mantener:
        sq = r.get("squeeze_state", "")
        sc = r.get("sqzm_color",    "")
        rows.append([
            r.get("ticker", ""),
            f"{r.get('score', 0):+.1f}",
            f"${r.get('price_usd', 0):.2f}",
            sq,
            sc,
            r.get("asset_subtype", ""),
        ])

    if rows:
        tbl = ax.table(
            cellText=rows,
            colLabels=["Ticker", "Score", "Precio", "Squeeze", "SQZM Color", "Sector"],
            loc="center", bbox=[0.02, 0.10, 0.96, 0.80],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8.5)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#eeeeee"); cell.set_text_props(fontweight="bold")
            else:
                cell.set_facecolor("white" if r % 2 == 0 else "#fafafa")
    return fig



