"""
actualizar_universo_etfs.py - Escribe src/universo_etfs.py (lista FIJA de acciones de calidad).

Se corre una vez, o cada trimestre tras los rebalanceos de los índices:
    python tools/actualizar_universo_etfs.py
o desde GitHub: Actions -> "Actualizar universo ETF" -> Run workflow.

Embudo:
  Base    S&P 1500 + holdings de SP500/QQQ/SOXX/XLV (EE.UU.), VXUS/MCHI/IWVL (internacional),
          REMX/BATT/QTUM/ICLN (temáticos) + lista LatAm. Solo lo que cotiza en NYSE/Nasdaq (ADRs incluidos).
  Capa 1  Tamaño y liquidez: cap. ≥ 5.000 M USD (emergentes 2.000 M), volumen ≥ 20 M USD/día
          (emergentes 5 M), precio ≥ 5 USD, ≥ 5 años cotizando.
  Capa 2  Sello de índice: EE.UU. en el S&P 1500; resto en VXUS/MCHI/IWVL o lista LatAm.
  Capa 3  Descarte: margen operativo < 0, FCF negativo 2 de 3 años, deuda neta/EBITDA > 3.5,
          dilución > 5%/año, ingresos cayendo. Bancos/aseguradoras: ROE ≥ 12% en vez de FCF y deuda.
  Capa 4  Puntaje 0-100 por categoría (rentabilidad, estabilidad del margen, crecimiento, balance);
          se queda el mejor 50% (70% en Emergentes).
  Aparte  Cupo "Especulativa" (máx. 40): en ETF temático, cap. ≥ 1.000 M, ingresos creciendo y caja
          para 2 años de pérdidas.

La corrida semanal (main.py) solo LEE src/universo_etfs.py: no consulta estas páginas.
Dependencias extra (solo para este script): requirements-universo.txt
"""
import io
import json
import os
import pprint
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]

# Top 25 de REMX (respaldo si VanEck no responde)
FONDOS = {
    "REMX": [
        ("SQM", "SQM", "Sociedad Química y Minera de Chile", 8.00),
        ("ALB", "ALB", "Albemarle", 7.98),
        ("MP", "MP", "MP Materials", 6.57),
        ("PLS", "PLS.AX", "Pilbara Minerals (PLS Group)", 6.13),
        ("LYC", "LYC.AX", "Lynas Rare Earths", 5.97),
        ("600111", "600111.SS", "China Northern Rare Earth", 5.76),
        ("601958", "601958.SS", "Jinduicheng Molybdenum", 4.75),
        ("600549", "600549.SS", "Xiamen Tungsten", 4.73),
        ("7610", ["7610.TWO", "7610.TW"], "Lianyou Metals", 4.51),
        ("ALM", ["ALM", "ALM.TO"], "Almonty Industries", 4.21),
        ("600392", "600392.SS", "Shenghe Resources", 3.72),
        ("ILU", "ILU.AX", "Iluka Resources", 3.44),
        ("LTR", "LTR.AX", "Liontown", 3.36),
        ("1772", "1772.HK", "Ganfeng Lithium", 3.34),
        ("EQR", "EQR.AX", "EQ Resources", 2.87),
        ("603663", "603663.SS", "Sanxiang Advanced Materials", 2.71),
        ("603067", "603067.SS", "Hubei Zhenhua Chemical", 2.60),
        ("AMG", "AMG.AS", "AMG Critical Materials", 2.45),
        ("LAC", "LAC", "Lithium Americas", 1.95),
        ("LAR", "LAR", "Lithium Argentina", 1.78),
        ("CXO", "CXO.AX", "Core Lithium", 1.66),
        ("ELVR", "ELVR.AX", "Elevra Lithium", 1.40),
        ("SGML", "SGML", "Sigma Lithium", 1.32),
        ("ERA", "ERA.PA", "Eramet", 1.19),
        ("IPX", "IPX", "IperionX", 1.18),
    ],
}

# =============================================================================
# FUENTES DE HOLDINGS POR ETF
# =============================================================================
# Arma el universo con las acciones que tiene cada ETF, se queda solo con las que
# se compran en una bolsa de EE.UU. (NYSE / Nasdaq / NYSE American: empresas de
# EE.UU. y ADRs) y las evalúa con el MISMO motor LP/MP de arriba.
#
# Cada ETF tiene una lista de fuentes que se prueban en orden. Si todas fallan,
# se usa un CSV propio en holdings/<ETF>.csv (lo descargas de la página del
# emisor: botón "Download holdings"). El reporte dice qué fuente usó cada ETF,
# para que sepas si la cobertura fue completa o parcial.

ETFS_REPORTE2 = ["SP500", "REMX", "SOXX", "QQQ", "QTUM", "BATT", "XLV", "MCHI", "VXUS", "IWVL", "ICLN"]
# Índices que funcionan como "sello de calidad" (capa 2). SP400/SP600 completan el S&P 1500.
FUENTES_BASE = ETFS_REPORTE2 + ["SP400", "SP600"]
CARPETA_HOLDINGS = str(RAIZ / "data" / "holdings")          # CSV manuales opcionales: holdings/SOXX.csv, holdings/VXUS.csv ...
# La SEC pide un User-Agent con nombre y correo de contacto. Pon el tuyo.
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "RecomendadorETF contacto@ejemplo.com")
UA_WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
BOLSAS_EEUU_SEC = {"NYSE", "Nasdaq", "NYSE American", "NYSE MKT", "CBOE", "BATS"}
MIN_FILAS_FUENTE = 5                   # una fuente con menos filas se considera fallida

_ISH_US = "https://www.ishares.com/us/products/{id}/x/1467271812596.ajax?fileType=csv&fileName={t}_holdings&dataType=fund"
_ISH_UK = "https://www.ishares.com/uk/individual/en/products/{id}/x/1506575576011.ajax?fileType=csv&fileName={t}_holdings&dataType=fund"

# (tipo, parámetro, nota). Se prueban en orden; la primera con datos gana.
FUENTES_ETF = {
    "SP500": [("wiki", ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"), "Wikipedia"),
              ("csv_local", str(RAIZ / "data" / "sp500_constituyentes.csv"), "CSV S&P 500 local")],
    "SP400": [("wiki", ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"), "Wikipedia (S&P 400)")],
    "SP600": [("wiki", ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "Symbol"), "Wikipedia (S&P 600)")],
    "QQQ":   [("wiki", ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"), "Wikipedia (Nasdaq-100)"),
              ("stockanalysis", "qqq", "StockAnalysis (top 25)")],
    "SOXX":  [("csv_url", _ISH_US.format(id=239705, t="SOXX"), "iShares")],
    "MCHI":  [("csv_url", _ISH_US.format(id=239619, t="MCHI"), "iShares")],
    "ICLN":  [("csv_url", _ISH_US.format(id=239738, t="ICLN"), "iShares")],
    "IWVL":  [("csv_url", _ISH_UK.format(id=270048, t="IWVL"), "iShares UK")],
    "XLV":   [("xlsx_url", "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlv.xlsx", "State Street")],
    "VXUS":  [("vanguard", "VXUS", "Vanguard"),
              ("csv_url", _ISH_US.format(id=244048, t="IXUS"), "iShares IXUS (proxy de VXUS: mismo universo internacional)")],
    "REMX":  [("xlsx_url", "https://www.vaneck.com/us/en/investments/rare-earth-strategic-metals-etf-remx/downloads/holdings/", "VanEck"),
              ("notebook", "REMX", "Lista REMX del notebook (top 25)")],
    "QTUM":  [("html", "https://www.defianceetfs.com/qtum-full-holdings/", "Defiance")],
    "BATT":  [("html", "https://amplifyetfs.com/batt-holdings/", "Amplify")],
}
# Respaldo común a todos (en este orden) cuando fallan las fuentes propias
RESPALDOS = [("csv_manual", None, "CSV manual en holdings/"),
             ("stockanalysis", None, "StockAnalysis (solo top 25)"),
             ("yf_top", None, "yfinance (solo top 10)")]


# ---------------------------------------------------------------------------
# Lectura de tablas de cualquier emisor -> columnas estándar
# ---------------------------------------------------------------------------
def _norm_col(c) -> str:
    c = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z%]+", " ", c).strip()


_ALIAS_COLS = {
    "ticker": ["ticker", "symbol", "holding ticker", "ticker symbol", "stock ticker", "issuer ticker"],
    "nombre": ["name", "holding name", "security name", "security", "company", "holding", "description",
               "issuer name", "long name", "longname"],
    "peso": ["weight %", "weight", "% of net assets", "etf weight", "weight (%)", "% weight", "percent weight",
             "percentweight", "% of funds", "market value weight", "% of fund", "portfolio weight", "weighting"],
    "pais": ["location", "country", "location of risk", "domicile"],
    "bolsa": ["exchange", "market", "primary exchange"],
    "clase": ["asset class", "security type", "asset type", "type"],
    "isin": ["isin"],
    "sector": ["gics sector", "sector"],
    "subind": ["gics sub industry", "sub industry", "industry"],
}


def normalizar_tabla(df: pd.DataFrame) -> pd.DataFrame | None:
    """Devuelve DataFrame [ticker, nombre, peso, pais, bolsa, clase, isin] o None si no reconoce la tabla."""
    if df is None or df.empty:
        return None
    cols = {_norm_col(c): c for c in df.columns}
    elegido = {}
    for std, alias in _ALIAS_COLS.items():
        for a in alias:
            a_n = _norm_col(a)
            if a_n in cols:
                elegido[std] = cols[a_n]
                break
        else:  # coincidencia parcial ("weight (%)" -> "weight")
            for n, orig in cols.items():
                if any(_norm_col(a) and n.startswith(_norm_col(a)) for a in alias) and orig not in elegido.values():
                    elegido[std] = orig
                    break
    if "ticker" not in elegido and "nombre" not in elegido:
        return None
    out = pd.DataFrame({k: df[v] for k, v in elegido.items()})
    for k in _ALIAS_COLS:
        if k not in out:
            out[k] = None
    out["ticker"] = out["ticker"].astype(str).str.strip().replace({"nan": None, "-": None, "": None, "None": None})
    out["nombre"] = out["nombre"].astype(str).str.strip()
    out["peso"] = pd.to_numeric(out["peso"].astype(str).str.replace("%", "").str.replace(",", "")
                                .str.strip(), errors="coerce")
    if out["peso"].notna().any() and out["peso"].max() <= 1.0 and out["peso"].sum() < 2:
        out["peso"] = out["peso"] * 100  # venía en fracción
    # Solo acciones (fuera efectivo, futuros, derivados, bonos)
    clase = out["clase"].astype(str).str.lower()
    tiene_clase = out["clase"].notna() & (clase != "none")
    es_accion = clase.str.contains("equity|stock|common|share|adr|gdr|reit", regex=True)
    out = out[~tiene_clase | es_accion]
    basura = out["nombre"].str.upper().str.contains(
        r"\bCASH\b|USD CASH|FUTURE|FUTURES|\bFX\b|CURRENCY|MONEY MARKET|TREASURY|SWAP|OTHER/|MARGIN|"
        r"BLK CSH|MKTLIQ|LIQUIDITY|COLLATERAL|DERIVATIVE|FORWARD", regex=True, na=False)
    out = out[~basura]
    out = out[~out["nombre"].isin(["nan", "", "None"]) & (out["ticker"].fillna("").str.len() <= 15)]
    return out[list(_ALIAS_COLS)].reset_index(drop=True)


def _tabla_desde_texto_csv(texto: str) -> pd.DataFrame | None:
    """Los CSV de iShares traen ~9 líneas de encabezado antes de la tabla."""
    lineas = texto.splitlines()
    ini = next((i for i, l in enumerate(lineas[:40])
                if re.match(r'^﻿?"?(Ticker|Symbol|Holding Ticker|Name)"?\s*,', l, re.I)), None)
    if ini is None:
        return None
    df = pd.read_csv(io.StringIO("\n".join(lineas[ini:])), on_bad_lines="skip", dtype=str)
    return df.dropna(how="all")


def _tabla_desde_excel(contenido: bytes) -> pd.DataFrame | None:
    """Busca la fila de encabezado (la que contiene Ticker/Name) en cualquier hoja."""
    hojas = pd.read_excel(io.BytesIO(contenido), sheet_name=None, header=None, dtype=str)
    for crudo in hojas.values():
        for i in range(min(len(crudo), 40)):
            fila = [_norm_col(x) for x in crudo.iloc[i].tolist()]
            if any(x in ("ticker", "symbol") for x in fila) and any(("name" in x) or x == "security" for x in fila):
                df = crudo.iloc[i + 1:].copy()
                df.columns = [str(x) for x in crudo.iloc[i].tolist()]
                return df.dropna(how="all")
    return None


def _get(url: str, headers=None, timeout=30) -> requests.Response:
    r = requests.get(url, headers=headers or UA_WEB, timeout=timeout)
    r.raise_for_status()
    return r


def _fuente(tipo: str, param, etf: str) -> pd.DataFrame | None:
    import yfinance as yf
    if tipo == "wiki":
        url, col = param
        for t in pd.read_html(io.StringIO(_get(url).text)):
            if col in t.columns:
                t = t.rename(columns={col: "Ticker"})
                nombre = next((c for c in ("Security", "Company", "Name") if c in t.columns), None)
                return pd.DataFrame({"Ticker": t["Ticker"], "Name": t[nombre] if nombre else t["Ticker"],
                                     "Location": "United States",
                                     "GICS Sector": t.get("GICS Sector"), "GICS Sub-Industry": t.get("GICS Sub-Industry")})
        return None
    if tipo == "csv_local":
        ruta = next((q for q in (Path(param), Path.home() / "Downloads" / Path(param).name) if q.exists()), None)
        if ruta is None:
            return None
        t = pd.read_csv(ruta)
        return pd.DataFrame({"Ticker": t["Symbol"], "Name": t["Security"], "Location": "United States",
                             "GICS Sector": t.get("GICS Sector"), "GICS Sub-Industry": t.get("GICS Sub-Industry")})
    if tipo == "csv_manual":
        ruta = Path(CARPETA_HOLDINGS) / f"{etf}.csv"
        if not ruta.exists():
            return None
        texto = ruta.read_text(encoding="utf-8-sig", errors="ignore")
        t = _tabla_desde_texto_csv(texto)
        return t if t is not None else pd.read_csv(io.StringIO(texto), dtype=str)
    if tipo == "csv_url":
        return _tabla_desde_texto_csv(_get(param).text)
    if tipo == "xlsx_url":
        r = _get(param)
        if r.content[:2] == b"PK":  # xlsx
            return _tabla_desde_excel(r.content)
        return _tabla_desde_texto_csv(r.text)
    if tipo == "html":
        tablas = pd.read_html(io.StringIO(_get(param).text))
        return max(tablas, key=len) if tablas else None
    if tipo == "vanguard":
        url = (f"https://investor.vanguard.com/investment-products/etfs/profile/api/{param}"
               f"/portfolio-holding/stock?start=1&count=20000")
        js = _get(url, headers={**UA_WEB, "Accept": "application/json"}).json()
        lista = _buscar_lista_dicts(js)
        return pd.DataFrame(lista) if lista else None
    if tipo == "notebook":
        return pd.DataFrame([{"Ticker": y if isinstance(y, str) else y[0], "Name": n, "Weight": p}
                             for _, y, n, p in FONDOS.get(param, [])])
    if tipo == "stockanalysis":
        clave = (param or etf).lower()
        if clave == "sp500":
            clave = "ivv"
        tablas = pd.read_html(io.StringIO(_get(f"https://stockanalysis.com/etf/{clave}/holdings/").text))
        return max(tablas, key=len) if tablas else None
    if tipo == "yf_top":
        clave = {"SP500": "IVV", "IWVL": "IWVL.L"}.get(etf, etf)
        th = yf.Ticker(clave).funds_data.top_holdings
        if th is None or th.empty:
            return None
        th = th.reset_index()
        return pd.DataFrame({"Ticker": th.iloc[:, 0], "Name": th.get("Name", th.iloc[:, 0]),
                             "Weight": th.get("Holding Percent", None)})
    return None


def _buscar_lista_dicts(obj):
    """Encuentra la lista de dicts más larga dentro de un JSON (formato Vanguard sin documentar)."""
    mejor = []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        mejor = obj
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, list):
        for x in obj:
            if isinstance(x, (dict, list)):
                cand = _buscar_lista_dicts(x)
                if len(cand) > len(mejor):
                    mejor = cand
    return mejor


def holdings_etf(etf: str) -> tuple[pd.DataFrame | None, str]:
    """Devuelve (tabla estándar, descripción de la fuente usada)."""
    errores = []
    for tipo, param, nota in FUENTES_ETF.get(etf, []) + RESPALDOS:
        try:
            t = normalizar_tabla(_fuente(tipo, param, etf))
        except Exception as e:  # noqa: BLE001 - una fuente caída no debe tumbar el reporte
            errores.append(f"{nota}: {type(e).__name__}")
            continue
        if t is not None and len(t) >= MIN_FILAS_FUENTE:
            parcial = tipo in ("stockanalysis", "yf_top", "notebook")
            return t, nota + (" ⚠ parcial" if parcial else "")
        errores.append(f"{nota}: sin tabla")
    return None, "SIN FUENTE (" + "; ".join(errores) + ")"


# ---------------------------------------------------------------------------
# ¿Se compra en EE.UU.?  Empresas de EE.UU. directo; extranjeras -> ADR por nombre
# ---------------------------------------------------------------------------
_PAL_VACIAS = set("""LTD LIMITED INC INCORPORATED CORP CORPORATION CO COMPANY PLC SA S A AG NV N V SE ASA AB
SPA S P A LP UNITS UNIT SUBORDINATE VOTING NON HOLDINGS HOLDING HLDGS GROUP GRP THE CLASS CL A B C H ADR ADS ORD REG SHS SHARES SPONSORED
DE LA DEL TBK BHD PCL KK OYJ AS A/S NPV PREF PFD GDR SAB CV CIA CO LTD. INTL INTERNATIONAL""".split())
_BOLSAS_US_ISHARES = ("nasdaq", "new york stock exchange", "nyse", "cboe", "bats", "nyse arca", "nyse mkt")
_SUFIJOS_BBG_US = {"US", "UW", "UN", "UQ", "UR", "UA", "UP", "UV"}

# ADRs conocidos que el emparejamiento por nombre podría fallar (nombre local ≠ nombre SEC).
# Clave: fragmento del nombre del holding en mayúsculas -> ticker EE.UU. (None = no cotiza en bolsa de EE.UU.)
ADR_MANUAL = {
    "TAIWAN SEMICONDUCTOR": "TSM", "ALIBABA": "BABA", "PDD HOLDINGS": "PDD", "JD.COM": "JD", "JD COM": "JD",
    "NETEASE": "NTES", "BAIDU": "BIDU", "TRIP.COM": "TCOM", "TRIP COM": "TCOM", "YUM CHINA": "YUMC",
    "NIO INC": "NIO", "LI AUTO": "LI", "XPENG": "XPEV", "BILIBILI": "BILI", "TENCENT MUSIC": "TME",
    "FULL TRUCK": "YMM", "KE HOLDINGS": "BEKE", "ZTO EXPRESS": "ZTO", "VIPSHOP": "VIPS", "BEIGENE": "ONC",
    "BEONE MEDICINES": "ONC", "H WORLD": "HTHT", "LEGEND BIOTECH": "LEGN",
    "TENCENT HOLDINGS": None, "MEITUAN": None, "XIAOMI": None, "BYD CO": None, "CHINA CONSTRUCTION BANK": None,
    "ASML": "ASML", "SAP SE": "SAP", "NOVO NORDISK": "NVO", "NOVARTIS": "NVS", "ASTRAZENECA": "AZN",
    "SHELL PLC": "SHEL", "HSBC": "HSBC", "UNILEVER": "UL", "BP PLC": "BP", "DIAGEO": "DEO", "GSK": "GSK",
    "BRITISH AMERICAN TOBACCO": "BTI", "RIO TINTO": "RIO", "BHP": "BHP", "SANOFI": "SNY", "TOTALENERGIES": "TTE",
    "UBS GROUP": "UBS", "BANCO SANTANDER": "SAN", "BANCO BILBAO": "BBVA", "ING GROEP": "ING",
    "TOYOTA MOTOR": "TM", "SONY": "SONY", "HONDA MOTOR": "HMC", "MITSUBISHI UFJ": "MUFG",
    "SUMITOMO MITSUI FINANCIAL": "SMFG", "MIZUHO": "MFG", "INFOSYS": "INFY", "HDFC BANK": "HDB",
    "ICICI BANK": "IBN", "WIPRO": "WIT", "DR REDDY": "RDY", "PETROBRAS": "PBR", "PETROLEO BRASILEIRO": "PBR",
    "VALE SA": "VALE", "ITAU UNIBANCO": "ITUB", "BANCO BRADESCO": "BBD", "AMBEV": "ABEV", "NU HOLDINGS": "NU",
    "MERCADOLIBRE": "MELI", "SEA LTD": "SE", "COUPANG": "CPNG", "GRAB": "GRAB",
    "SAMSUNG ELECTRONICS": None, "NESTLE": None, "ROCHE": None, "LVMH": None, "SIEMENS AG": None,
    "ANGLOGOLD": "AU", "GOLD FIELDS": "GFI", "SASOL": "SSL", "KB FINANCIAL": "KB", "SHINHAN": "SHG",
    "POSCO": "PKX", "KOREA ELECTRIC": "KEP", "UNITED MICROELECTRONICS": "UMC", "ASE TECHNOLOGY": "ASX",
    "CHUNGHWA TELECOM": "CHT", "SOCIEDAD QUIMICA": "SQM", "ARM HOLDINGS": "ARM", "SPOTIFY": "SPOT",
    "FERRARI": "RACE", "STELLANTIS": "STLA", "ARCELORMITTAL": "MT", "NOKIA": "NOK", "ERICSSON": "ERIC",
    "BARCLAYS": "BCS", "LLOYDS BANKING": "LYG", "NATWEST": "NWG", "RELX": "RELX", "ARGENX": "ARGX",
    "CANADIAN PACIFIC": "CP", "CANADIAN NATIONAL": "CNI", "ROYAL BANK OF CANADA": "RY",
    "TORONTO DOMINION": "TD", "SHOPIFY": "SHOP", "ENBRIDGE": "ENB", "BROOKFIELD CORP": "BN",
    "CANADIAN NATURAL": "CNQ", "BANK OF MONTREAL": "BMO", "BANK OF NOVA SCOTIA": "BNS",
    "SUNCOR": "SU", "CAMECO": "CCJ", "NUTRIEN": "NTR", "AGNICO EAGLE": "AEM", "BARRICK": "B",
    "WHEATON PRECIOUS": "WPM", "FRANCO NEVADA": "FNV", "MANULIFE": "MFC", "SUN LIFE": "SLF",
    "THOMSON REUTERS": "TRI", "WASTE CONNECTIONS": "WCN", "CGI INC": "GIB", "TC ENERGY": "TRP",
}


def _norm_nombre(n: str) -> str:
    n = unicodedata.normalize("NFKD", str(n)).encode("ascii", "ignore").decode().upper()
    n = re.sub(r"[^A-Z0-9 ]+", " ", n)
    return " ".join(p for p in n.split() if p not in _PAL_VACIAS)


def cargar_sec() -> tuple[set[str], dict[str, str]]:
    """(tickers listados en bolsa de EE.UU., nombre normalizado -> ticker). Vacío si la SEC no responde."""
    try:
        js = _get("https://www.sec.gov/files/company_tickers_exchange.json",
                  headers={"User-Agent": SEC_USER_AGENT}).json()
    except Exception as e:  # noqa: BLE001
        print(f"Aviso: no pude leer la lista de la SEC ({type(e).__name__}); "
              "uso solo ADR_MANUAL y el campo de bolsa de yfinance para filtrar.")
        return set(), {}
    campos = js["fields"]
    df = pd.DataFrame(js["data"], columns=campos)
    df = df[df["exchange"].isin(BOLSAS_EEUU_SEC)]
    listados = set(df["ticker"].str.upper())
    por_nombre: dict[str, str] = {}
    # Un CIK puede tener varios tickers (preferentes, warrants): se prefiere el más corto sin guion
    df = df.assign(_k=df["ticker"].str.contains("-").astype(int), _l=df["ticker"].str.len())
    for _, f in df.sort_values(["cik", "_k", "_l"]).drop_duplicates("cik").iterrows():
        clave = _norm_nombre(f["name"])
        if clave and clave not in por_nombre:
            por_nombre[clave] = f["ticker"].upper()
    return listados, por_nombre


def _es_eeuu(fila) -> bool | None:
    # La bolsa manda sobre el país: un ADR (TSM, ASML) figura con país extranjero pero cotiza en EE.UU.
    bolsa = str(fila.get("bolsa") or "").lower()
    if bolsa and bolsa not in ("none", "nan", "-"):
        return any(b in bolsa for b in _BOLSAS_US_ISHARES)
    pais = str(fila.get("pais") or "").lower()
    if pais and pais not in ("none", "nan", "-"):
        return pais in ("united states", "usa", "us", "estados unidos")
    t = str(fila.get("ticker") or "")
    if " " in t:  # formato Bloomberg "3443 TT"
        return t.split()[-1].upper() in _SUFIJOS_BBG_US
    if re.search(r"\.[A-Z]{1,3}$", t) or t.isdigit():
        return False
    return None  # no se sabe: lo decide la lista de la SEC / yfinance


def buscar_adr(nombre: str, por_nombre: dict[str, str]) -> str | None:
    up = str(nombre).upper()
    for frag, tk in ADR_MANUAL.items():
        if frag in up:
            return tk
    clave = _norm_nombre(nombre)
    if not clave:
        return None
    if clave in por_nombre:
        return por_nombre[clave]
    # prefijo con al menos 2 palabras y 8 letras ("TOYOTA MOTOR" vs "TOYOTA MOTOR CORP")
    if len(clave.split()) >= 2 and len(clave) >= 8:
        cands = {tk for k, tk in por_nombre.items() if k.startswith(clave + " ") or clave.startswith(k + " ")}
        if len(cands) == 1:
            return cands.pop()
    return None


def _sym_yahoo_us(t: str) -> str:
    t = str(t).strip().upper()
    if " " in t:
        t = t.split()[0]
    return t.replace(".", "-").replace("/", "-")  # BRK.B / BRK/B -> BRK-B


def construir_universo(etfs=ETFS_REPORTE2):
    """
    Devuelve (activos, cobertura):
      activos   = lista de dicts {ticker, nombre, etfs, sector_etf, subind_etf}, sin duplicados
      cobertura = DataFrame por ETF con fuente, holdings, comprables en EE.UU. y descartadas
    """
    listados, por_nombre = cargar_sec()
    universo: dict[str, dict] = {}
    cobertura = []
    for etf in etfs:
        t, fuente = holdings_etf(etf)
        if t is None:
            cobertura.append({"ETF": etf, "Fuente": fuente, "Holdings": 0, "Comprables EE.UU.": 0,
                              "Sin listado EE.UU.": 0})
            print(f"  {etf:<6} ✘ {fuente}")
            continue
        ok, fuera = 0, []
        for _, f in t.iterrows():
            f = f.to_dict()
            us = _es_eeuu(f)
            sym = None
            if us is True and f["ticker"]:
                sym = _sym_yahoo_us(f["ticker"])
            elif us is False:
                sym = buscar_adr(f["nombre"], por_nombre)
            else:  # desconocido: ticker si está listado en EE.UU.; si no, ADR por nombre
                cand = _sym_yahoo_us(f["ticker"]) if f["ticker"] else None
                if cand and (not listados or cand.replace("-", ".") in listados or cand in listados):
                    sym = cand
                else:
                    sym = buscar_adr(f["nombre"], por_nombre)
            if sym and listados and sym not in listados:
                # iShares escribe BRKB / BFB para las clases: probar BRK-B
                alt = sym[:-1] + "-" + sym[-1] if len(sym) >= 3 and "-" not in sym else None
                if alt and alt in listados:
                    sym = alt
                elif sym.replace("-", "") in listados:
                    sym = sym.replace("-", "")
                else:
                    sym = None  # no está en NYSE/Nasdaq (OTC o deslistado)
            if not sym:
                fuera.append(f["nombre"])
                continue
            ok += 1
            u = universo.setdefault(sym, {"nombre": f["nombre"], "etfs": {}, "sector": None, "subind": None})
            for k in ("sector", "subind"):
                v = f.get(k)
                if not u[k] and v is not None and str(v) not in ("nan", "None", "-", ""):
                    u[k] = str(v)
            peso = f["peso"] if f["peso"] is not None and not pd.isna(f["peso"]) else None
            u["etfs"][etf] = max(peso or 0, u["etfs"].get(etf) or 0) or None
        cobertura.append({"ETF": etf, "Fuente": fuente, "Holdings": len(t), "Comprables EE.UU.": ok,
                          "Sin listado EE.UU.": len(fuera)})
        print(f"  {etf:<6} {fuente:<45} holdings {len(t):>5} · comprables EE.UU. {ok:>5}")

    activos = []
    for sym, u in universo.items():
        orden = sorted(u["etfs"].items(), key=lambda kv: -(kv[1] or 0))
        origen = ", ".join(f"{e} {p:.2f}%" if p else e for e, p in orden)
        activos.append({"ticker": sym, "nombre": u["nombre"], "etfs": origen,
                        "sector_etf": u["sector"], "subind_etf": u["subind"]})
    return activos, pd.DataFrame(cobertura)


# =============================================================================
# FICHAS DE EMPRESA (actividad, país, tipo, descripción) y escritura del archivo
# =============================================================================

ARCHIVO_UNIVERSO = str(RAIZ / "src" / "universo_etfs.py")
CACHE_FICHAS = str(RAIZ / "data" / "universo_fichas_cache.json")  # permite retomar si Yahoo corta
MODELO_GROQ = "llama-3.3-70b-versatile"

SECTORES_ES = {
    "Technology": "Tecnología", "Healthcare": "Salud", "Financial Services": "Financiero",
    "Consumer Cyclical": "Consumo discrecional", "Consumer Defensive": "Consumo básico",
    "Industrials": "Industrial", "Energy": "Energía", "Utilities": "Servicios públicos",
    "Real Estate": "Inmobiliario", "Basic Materials": "Materiales básicos",
    "Communication Services": "Comunicaciones",
    # nombres GICS (Wikipedia / iShares / State Street)
    "Information Technology": "Tecnología", "Health Care": "Salud", "Financials": "Financiero",
    "Consumer Discretionary": "Consumo discrecional", "Consumer Staples": "Consumo básico",
    "Materials": "Materiales básicos",
}
# Súper-sectores de Morningstar: comportamiento frente al ciclo económico
CICLO = {
    "Materiales básicos": "Cíclica", "Consumo discrecional": "Cíclica", "Financiero": "Cíclica",
    "Inmobiliario": "Cíclica", "Comunicaciones": "Sensible al ciclo", "Energía": "Sensible al ciclo",
    "Industrial": "Sensible al ciclo", "Tecnología": "Sensible al ciclo",
    "Consumo básico": "Defensiva", "Salud": "Defensiva", "Servicios públicos": "Defensiva",
}
# Industrias de Yahoo Finance -> actividad en español (lo que hace la empresa, en 2–4 palabras)
ACTIVIDAD_ES = {
    "Advertising Agencies": "Agencias de publicidad", "Aerospace & Defense": "Aeroespacial y defensa",
    "Agricultural Inputs": "Insumos agrícolas (fertilizantes)", "Airlines": "Aerolíneas",
    "Airports & Air Services": "Aeropuertos y servicios aéreos", "Aluminum": "Minería y producción de aluminio",
    "Apparel Manufacturing": "Fabricación de ropa", "Apparel Retail": "Tiendas de ropa",
    "Asset Management": "Gestión de activos", "Auto & Truck Dealerships": "Concesionarios de vehículos",
    "Auto Manufacturers": "Fabricante de vehículos", "Auto Parts": "Autopartes",
    "Banks - Diversified": "Banca diversificada", "Banks - Regional": "Banca regional",
    "Beverages - Brewers": "Cervecería", "Beverages - Non-Alcoholic": "Bebidas no alcohólicas",
    "Beverages - Wineries & Distilleries": "Vinos y licores", "Biotechnology": "Biotecnología",
    "Broadcasting": "Radio y televisión", "Building Materials": "Materiales de construcción",
    "Building Products & Equipment": "Productos y equipos para construcción",
    "Business Equipment & Supplies": "Equipos y suministros de oficina", "Capital Markets": "Banca de inversión y corretaje",
    "Chemicals": "Químicos", "Coking Coal": "Minería de carbón metalúrgico",
    "Communication Equipment": "Equipos de comunicaciones", "Computer Hardware": "Hardware y computadores",
    "Confectioners": "Confitería y chocolates", "Conglomerates": "Conglomerado",
    "Consulting Services": "Consultoría", "Consumer Electronics": "Electrónica de consumo",
    "Copper": "Minería de cobre", "Credit Services": "Tarjetas y servicios de crédito",
    "Department Stores": "Tiendas por departamentos", "Diagnostics & Research": "Diagnóstico e investigación médica",
    "Discount Stores": "Supermercados de descuento", "Drug Manufacturers - General": "Farmacéutica",
    "Drug Manufacturers - Specialty & Generic": "Farmacéutica especializada y genéricos",
    "Education & Training Services": "Educación", "Electrical Equipment & Parts": "Equipos eléctricos",
    "Electronic Components": "Componentes electrónicos", "Electronic Gaming & Multimedia": "Videojuegos",
    "Electronics & Computer Distribution": "Distribución de electrónica",
    "Engineering & Construction": "Ingeniería y construcción", "Entertainment": "Entretenimiento y medios",
    "Farm & Heavy Construction Machinery": "Maquinaria agrícola y pesada", "Farm Products": "Productos agrícolas",
    "Financial Conglomerates": "Conglomerado financiero", "Financial Data & Stock Exchanges": "Bolsas y datos financieros",
    "Food Distribution": "Distribución de alimentos", "Footwear & Accessories": "Calzado y accesorios",
    "Furnishings, Fixtures & Appliances": "Muebles y electrodomésticos", "Gambling": "Apuestas",
    "Gold": "Minería de oro", "Grocery Stores": "Supermercados", "Health Information Services": "Software y datos de salud",
    "Healthcare Plans": "Aseguradora de salud", "Home Improvement Retail": "Tiendas de mejoras para el hogar",
    "Household & Personal Products": "Productos de hogar y cuidado personal",
    "Industrial Distribution": "Distribución industrial", "Information Technology Services": "Servicios de TI",
    "Infrastructure Operations": "Operación de infraestructura", "Insurance - Diversified": "Seguros diversificados",
    "Insurance - Life": "Seguros de vida", "Insurance - Property & Casualty": "Seguros de daños",
    "Insurance - Reinsurance": "Reaseguros", "Insurance - Specialty": "Seguros especializados",
    "Insurance Brokers": "Corredor de seguros", "Integrated Freight & Logistics": "Logística y paquetería",
    "Internet Content & Information": "Internet y redes sociales", "Internet Retail": "Comercio electrónico",
    "Leisure": "Ocio y recreación", "Lodging": "Hoteles", "Lumber & Wood Production": "Madera",
    "Luxury Goods": "Artículos de lujo", "Marine Shipping": "Transporte marítimo",
    "Medical Care Facilities": "Hospitales y clínicas", "Medical Devices": "Dispositivos médicos",
    "Medical Distribution": "Distribución médica", "Medical Instruments & Supplies": "Instrumental y suministros médicos",
    "Metal Fabrication": "Fabricación metálica", "Mortgage Finance": "Créditos hipotecarios",
    "Oil & Gas Drilling": "Perforación petrolera", "Oil & Gas E&P": "Exploración y producción de petróleo y gas",
    "Oil & Gas Equipment & Services": "Servicios petroleros", "Oil & Gas Integrated": "Petrolera integrada",
    "Oil & Gas Midstream": "Oleoductos y gasoductos", "Oil & Gas Refining & Marketing": "Refinación de petróleo",
    "Other Industrial Metals & Mining": "Minería de metales industriales (litio, tierras raras…)",
    "Other Precious Metals & Mining": "Minería de metales preciosos", "Packaged Foods": "Alimentos empacados",
    "Packaging & Containers": "Empaques y envases", "Paper & Paper Products": "Papel",
    "Personal Services": "Servicios personales", "Pharmaceutical Retailers": "Farmacias",
    "Pollution & Treatment Controls": "Control de contaminación", "Publishing": "Editorial",
    "Railroads": "Ferrocarriles", "Real Estate - Development": "Desarrollo inmobiliario",
    "Real Estate - Diversified": "Inmobiliario diversificado", "Real Estate Services": "Servicios inmobiliarios",
    "Recreational Vehicles": "Vehículos recreativos", "REIT - Diversified": "REIT diversificado",
    "REIT - Healthcare Facilities": "REIT de salud", "REIT - Hotel & Motel": "REIT hotelero",
    "REIT - Industrial": "REIT industrial (bodegas)", "REIT - Mortgage": "REIT hipotecario",
    "REIT - Office": "REIT de oficinas", "REIT - Residential": "REIT residencial", "REIT - Retail": "REIT comercial",
    "REIT - Specialty": "REIT especializado (torres, data centers)", "Rental & Leasing Services": "Alquiler de equipos",
    "Residential Construction": "Construcción de vivienda", "Resorts & Casinos": "Resorts y casinos",
    "Restaurants": "Restaurantes", "Scientific & Technical Instruments": "Instrumentos científicos y técnicos",
    "Security & Protection Services": "Seguridad", "Semiconductor Equipment & Materials": "Equipos para semiconductores",
    "Semiconductors": "Semiconductores (chips)", "Silver": "Minería de plata",
    "Software - Application": "Software de aplicaciones", "Software - Infrastructure": "Software de infraestructura",
    "Solar": "Energía solar", "Specialty Business Services": "Servicios empresariales",
    "Specialty Chemicals": "Químicos especializados", "Specialty Industrial Machinery": "Maquinaria industrial",
    "Specialty Retail": "Comercio especializado", "Staffing & Employment Services": "Empleo temporal",
    "Steel": "Acero", "Telecom Services": "Telecomunicaciones", "Textile Manufacturing": "Textiles",
    "Thermal Coal": "Minería de carbón", "Tobacco": "Tabaco", "Tools & Accessories": "Herramientas",
    "Travel Services": "Viajes y turismo", "Trucking": "Transporte de carga por carretera", "Uranium": "Minería de uranio",
    "Utilities - Diversified": "Servicios públicos diversificados",
    "Utilities - Independent Power Producers": "Generación eléctrica independiente",
    "Utilities - Regulated Electric": "Electricidad", "Utilities - Regulated Gas": "Distribución de gas",
    "Utilities - Regulated Water": "Acueducto", "Utilities - Renewable": "Energía renovable",
    "Waste Management": "Gestión de residuos",
}
# Respaldo si Yahoo no responde: sub-industrias GICS (vienen en los holdings del S&P 500 / iShares)
ACTIVIDAD_ES.update({
    "Passenger Airlines": "Aerolíneas", "Health Care Facilities": "Hospitales y clínicas",
    "Health Care Equipment": "Equipos médicos", "Health Care Supplies": "Suministros médicos",
    "Managed Health Care": "Aseguradora de salud", "Pharmaceuticals": "Farmacéutica",
    "Life Sciences Tools & Services": "Herramientas para ciencias de la vida",
    "Gold": "Minería de oro", "Copper": "Minería de cobre", "Steel": "Acero",
    "Diversified Metals & Mining": "Minería diversificada", "Fertilizers & Agricultural Chemicals": "Fertilizantes",
    "Oil & Gas Storage & Transportation": "Oleoductos y gasoductos",
    "Oil & Gas Exploration & Production": "Exploración y producción de petróleo y gas",
    "Integrated Oil & Gas": "Petrolera integrada", "Oil & Gas Refining & Marketing": "Refinación de petróleo",
    "Electric Utilities": "Electricidad", "Multi-Utilities": "Servicios públicos diversificados",
    "Renewable Electricity": "Energía renovable", "Semiconductor Materials & Equipment": "Equipos para semiconductores",
    "Application Software": "Software de aplicaciones", "Systems Software": "Software de infraestructura",
    "Electronic Components": "Componentes electrónicos", "Electronic Equipment & Instruments": "Instrumentos electrónicos",
    "Technology Hardware, Storage & Peripherals": "Hardware y computadores",
    "Aerospace & Defense": "Aeroespacial y defensa", "Construction & Engineering": "Ingeniería y construcción",
    "Electrical Components & Equipment": "Equipos eléctricos", "Industrial Machinery & Supplies & Components": "Maquinaria industrial",
    "Rail Transportation": "Ferrocarriles", "Air Freight & Logistics": "Logística y paquetería",
    "Property & Casualty Insurance": "Seguros de daños", "Life & Health Insurance": "Seguros de vida",
    "Diversified Banks": "Banca diversificada", "Regional Banks": "Banca regional",
    "Investment Banking & Brokerage": "Banca de inversión y corretaje", "Asset Management & Custody Banks": "Gestión de activos",
    "Transaction & Payment Processing Services": "Pagos electrónicos", "Consumer Finance": "Tarjetas y servicios de crédito",
    "Interactive Media & Services": "Internet y redes sociales", "Broadline Retail": "Comercio electrónico y tiendas",
    "Restaurants": "Restaurantes", "Automobile Manufacturers": "Fabricante de vehículos",
    "Hotels, Resorts & Cruise Lines": "Hoteles y cruceros", "Packaged Foods & Meats": "Alimentos empacados",
    "Soft Drinks & Non-alcoholic Beverages": "Bebidas no alcohólicas", "Tobacco": "Tabaco",
    "Movies & Entertainment": "Entretenimiento y medios", "Integrated Telecommunication Services": "Telecomunicaciones",
    "Biotechnology": "Biotecnología", "Semiconductors": "Semiconductores (chips)",
})
PAISES_ES = {
    "United States": "EE.UU.", "China": "China", "Taiwan": "Taiwán", "Hong Kong": "Hong Kong",
    "Japan": "Japón", "South Korea": "Corea del Sur", "India": "India", "United Kingdom": "Reino Unido",
    "Germany": "Alemania", "France": "Francia", "Netherlands": "Países Bajos", "Switzerland": "Suiza",
    "Ireland": "Irlanda", "Canada": "Canadá", "Australia": "Australia", "Brazil": "Brasil",
    "Mexico": "México", "Chile": "Chile", "Argentina": "Argentina", "Colombia": "Colombia", "Peru": "Perú",
    "Spain": "España", "Italy": "Italia", "Denmark": "Dinamarca", "Sweden": "Suecia", "Norway": "Noruega",
    "Finland": "Finlandia", "Belgium": "Bélgica", "Israel": "Israel", "Singapore": "Singapur",
    "South Africa": "Sudáfrica", "Luxembourg": "Luxemburgo", "Bermuda": "Bermudas",
    "Cayman Islands": "Islas Caimán", "Jersey": "Jersey", "Uruguay": "Uruguay", "Greece": "Grecia",
    "Indonesia": "Indonesia", "Philippines": "Filipinas", "Thailand": "Tailandia", "Austria": "Austria",
}
BOLSAS_EEUU_YF = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "NAS", "NYS", "NYSE", "NASDAQ", "AMEX"}


def _f(x):
    try:
        x = float(x)
        return None if np.isnan(x) else x
    except (TypeError, ValueError):
        return None


def obtener_info(sym: str, reintentos=3) -> dict | None:
    """Ficha de Yahoo con reintentos (Yahoo limita la frecuencia). None si no respondió."""
    import yfinance as yf
    for intento in range(reintentos):
        try:
            i = yf.Ticker(sym).info or {}
            if i.get("quoteType") or i.get("longName") or i.get("shortName"):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 * (intento + 1))
    else:
        return None
    precio = _f(i.get("currentPrice")) or _f(i.get("regularMarketPrice"))
    div = _f(i.get("trailingAnnualDividendYield"))
    if div is None and _f(i.get("dividendRate")) and precio:
        div = _f(i.get("dividendRate")) / precio
    return {
        "nombre": i.get("longName") or i.get("shortName"), "pais": i.get("country"),
        "sector": i.get("sector"), "industria": i.get("industry"), "quote_type": i.get("quoteType"),
        "bolsa": i.get("exchange"), "cap": _f(i.get("marketCap")), "pe": _f(i.get("trailingPE")),
        "pe_fwd": _f(i.get("forwardPE")), "pb": _f(i.get("priceToBook")), "div": div,
        "crec_ingresos": _f(i.get("revenueGrowth")), "crec_utilidad": _f(i.get("earningsGrowth")),
        "resumen": i.get("longBusinessSummary") or "",
        "precio": precio, "vol_prom": _f(i.get("averageVolume")) or _f(i.get("averageDailyVolume3Month")),
        "primer_dia": _f(i.get("firstTradeDateEpochUtc")) or (
            _f(i.get("firstTradeDateMilliseconds")) / 1000 if _f(i.get("firstTradeDateMilliseconds")) else None),
        "margen_op": _f(i.get("operatingMargins")), "roe": _f(i.get("returnOnEquity")),
        "deuda": _f(i.get("totalDebt")), "caja": _f(i.get("totalCash")), "ebitda": _f(i.get("ebitda")),
    }


def tamano(cap: float | None) -> str:
    if cap is None:
        return "Cap. N/D"
    return "Mega cap" if cap >= 200e9 else "Large cap" if cap >= 10e9 else "Mid cap" if cap >= 2e9 else "Small cap"


def estilo_accion(inf: dict) -> tuple[str, str]:
    """(estilo, por qué). Reglas simples y visibles."""
    g_ing, g_ut = inf.get("crec_ingresos"), inf.get("crec_utilidad")
    pe = inf.get("pe_fwd") or inf.get("pe")
    pb, div = inf.get("pb"), inf.get("div") or 0
    crece = (g_ing is not None and g_ing >= 0.15) or (g_ut is not None and g_ut >= 0.20 and (g_ing or 0) > 0.05)
    barata = pe is not None and 0 < pe < 15 and (pb is None or pb < 2.5)
    renta = div >= 0.03
    sin_utilidad = inf.get("pe") is None and inf.get("pe_fwd") is None
    motivos = []
    if g_ing is not None:
        motivos.append(f"ingresos {g_ing:+.0%} a/a")
    if pe is not None:
        motivos.append(f"P/U {pe:.1f}")
    if div:
        motivos.append(f"dividendo {div:.1%}")
    if crece and sin_utilidad:
        estilo = "Crecimiento especulativo"
    elif crece and barata:
        estilo = "Crecimiento a precio razonable"
    elif crece:
        estilo = "Crecimiento"
    elif barata and renta:
        estilo = "Valor / Dividendo"
    elif renta:
        estilo = "Dividendo"
    elif barata:
        estilo = "Valor"
    else:
        estilo = "Núcleo (mixta)"
    return estilo, ", ".join(motivos)


def _primeras_frases(texto: str, max_chars=260) -> str:
    out = ""
    for f in re.split(r"(?<=[.!?])\s+", str(texto).strip()):
        if len(out) + len(f) > max_chars and out:
            break
        out = (out + " " + f).strip()
    return out[:max_chars]


def _clave_groq() -> str | None:
    k = os.environ.get("GROQ_API_KEY")
    if k:
        return k
    try:
        from google.colab import userdata  # type: ignore
        return userdata.get("GROQ_API_KEY")
    except Exception:  # noqa: BLE001
        return None


def _describir_groq(lote: dict[str, dict], clave: str) -> dict[str, str]:
    entrada = {t: {"empresa": d["nombre"], "sector": d["sector"], "industria": d["industria"],
                   "resumen_en": _primeras_frases(d["resumen"], 700)} for t, d in lote.items()}
    prompt = ("Para cada ticker escribe UNA frase en español (máximo 28 palabras) que explique qué hace la "
              "empresa y de dónde vienen sus ingresos. Sin opiniones, sin recomendaciones, sin cifras ni fechas. "
              "Usa solo la información dada. Responde SOLO un JSON {ticker: frase}.\n\n"
              + json.dumps(entrada, ensure_ascii=False))
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=60,
                      headers={"Authorization": f"Bearer {clave}"},
                      json={"model": MODELO_GROQ, "temperature": 0.1, "response_format": {"type": "json_object"},
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    m = re.search(r"\{.*\}", r.json()["choices"][0]["message"]["content"], re.S)
    datos = json.loads(m.group(0)) if m else {}
    return {t: str(v).strip()[:260] for t, v in datos.items() if t in lote and isinstance(v, str) and v.strip()}


def _traducir(textos: list[str]) -> list[str | None]:
    try:
        from deep_translator import GoogleTranslator  # pip install deep-translator
    except ImportError:
        return [None] * len(textos)
    tr, out = GoogleTranslator(source="en", target="es"), []
    for t in textos:
        try:
            out.append(tr.translate(t) if t else None)
        except Exception:  # noqa: BLE001
            out.append(None)
    return out


def describir(infos: dict[str, dict]) -> dict[str, str]:
    """ticker -> descripción en español. Groq -> traductor -> resumen en inglés."""
    res: dict[str, str] = {}
    pendientes = {t: d for t, d in infos.items() if d.get("resumen")}
    clave = _clave_groq()
    if clave:
        items = list(pendientes.items())
        for i in range(0, len(items), 15):
            try:
                res.update(_describir_groq(dict(items[i:i + 15]), clave))
            except Exception as e:  # noqa: BLE001
                print(f"Aviso: Groq no respondió ({type(e).__name__}); sigo con el traductor.")
                break
    faltan = [t for t in pendientes if t not in res]
    originales = [_primeras_frases(pendientes[t]["resumen"]) for t in faltan]
    for t, orig, trad in zip(faltan, originales, _traducir(originales)):
        res[t] = trad or orig
    return res


def _ficha(a: dict, inf: dict | None, desc: str | None) -> dict:
    """Arma la ficha fija de una acción; usa lo del ETF (GICS) si Yahoo no respondió."""
    inf = inf or {}
    sector = SECTORES_ES.get(inf.get("sector") or a.get("sector_etf") or "", inf.get("sector") or a.get("sector_etf") or "N/D")
    ind_en = inf.get("industria") or a.get("subind_etf")
    actividad = ACTIVIDAD_ES.get(ind_en or "", ind_en or sector)
    estilo, por_que = estilo_accion(inf) if inf else ("N/D", "")
    pais = PAISES_ES.get(inf.get("pais") or "", inf.get("pais") or "N/D")
    if not desc:
        que = f"del sector {sector.lower()}" if actividad == sector else f"de {actividad.lower()} (sector {sector.lower()})"
        desc = f"Empresa {que}" + (f" con sede en {pais}." if pais != "N/D" else ".")
    return {"empresa": inf.get("nombre") or a["nombre"], "pais": pais, "sector": sector, "actividad": actividad,
            "estilo": estilo, "por_que": por_que, "tamano": tamano(inf.get("cap")), "ciclo": CICLO.get(sector, ""),
            "descripcion": desc, "etfs": a["etfs"]}


# =============================================================================
# FILTRO DE CALIDAD (capas 1-4) — solo se corre al actualizar el universo
# =============================================================================
# Capa 1  Tamaño y liquidez: capitalización, volumen en USD, precio, historia.
# Capa 2  Sello externo: EE.UU. -> S&P 1500 (el S&P exige utilidades para entrar);
#         fuera de EE.UU. -> índice internacional (VXUS/IXUS, MCHI, IWVL) o lista LatAm.
# Capa 3  Descarte duro de fundamentales (reglas propias para bancos/aseguradoras).
# Capa 4  Puntaje 0-100 dentro de cada categoría y se queda el mejor tramo.
# Aparte: cupo "Especulativa" para temas sin utilidades (tierras raras, litio, cuántica).

INDICES_EEUU = {"SP500", "SP400", "SP600"}
INDICES_INTL = {"VXUS", "MCHI", "IWVL"}
TEMATICOS = {"REMX", "BATT", "QTUM", "ICLN"}

# Países del MSCI Emerging Markets (+ Hong Kong, sede de muchas empresas chinas)
PAISES_EM = {
    "China", "Hong Kong", "Taiwan", "India", "South Korea", "Brazil", "Saudi Arabia", "South Africa",
    "Mexico", "Indonesia", "Thailand", "Malaysia", "United Arab Emirates", "Poland", "Qatar", "Kuwait",
    "Turkey", "Philippines", "Chile", "Greece", "Peru", "Hungary", "Czech Republic", "Colombia", "Egypt",
    "Argentina",
}
# Negocio latinoamericano con sede en otro país (Yahoo les asigna la sede). Editable.
LATAM_EM = {"MELI", "NU", "GLOB", "DLO", "STNE", "PAGS", "XP", "CPA", "BAP", "SCCO"}

MINERIA = {"Other Industrial Metals & Mining", "Copper", "Gold", "Silver", "Other Precious Metals & Mining",
           "Aluminum", "Uranium", "Steel", "Coking Coal"}
DEFENSIVOS = {"Healthcare", "Consumer Defensive", "Utilities"}
SECTORIALES = {"Energy", "Industrials", "Basic Materials"}
CON_CRECIMIENTO = {"Consumer Cyclical", "Communication Services", "Financial Services"}

# Umbrales (todos ajustables)
CAP_MIN = {"general": 5e9, "Emergentes": 2e9, "Especulativa": 1e9}
VOL_USD_MIN = {"general": 20e6, "Emergentes": 5e6, "Especulativa": 5e6}
PRECIO_MIN = 5.0
ANIOS_HISTORIA = 5
DEUDA_EBITDA_MAX = 3.5
DILUCION_MAX = 0.05          # crecimiento anual compuesto de acciones en circulación
ROE_MIN_FINANCIERAS = 0.12
CRECIMIENTO_MIN = 0.15       # para la categoría Crecimiento (consumo, comunicaciones, financieras)
TRAMO = {"general": 0.50, "Emergentes": 0.70}   # se queda el mejor 50% (70% en emergentes)
MAX_ESPECULATIVAS = 40


def _categoria(inf: dict, tags: set, sym: str) -> str | None:
    pais, sector, ind = inf.get("pais"), inf.get("sector"), inf.get("industria")
    if pais in PAISES_EM or sym in LATAM_EM:
        return "Emergentes"
    if ind in MINERIA or (sector == "Basic Materials" and tags & {"REMX", "BATT"}):
        return "Tierras raras y minería"
    if sector == "Technology":
        return "Tecnología"
    if sector in DEFENSIVOS:
        return "Defensivas"
    if sector in SECTORIALES:
        return "Sectoriales"
    if sector in CON_CRECIMIENTO and (inf.get("crec_ingresos") or 0) >= CRECIMIENTO_MIN:
        return "Crecimiento"
    return None   # inmobiliario, bancos de EE.UU. sin crecimiento, etc.


def obtener_estados(sym: str, reintentos=2) -> dict:
    """Series anuales (más reciente primero) de ingresos, utilidad operativa, FCF, acciones y capital invertido."""
    import yfinance as yf

    def fila(df, nombres):
        if df is None or getattr(df, "empty", True):
            return []
        for n in nombres:
            if n in df.index:
                return [x for x in (_f(v) for v in df.loc[n].tolist()) if x is not None][:4]
        return []

    for intento in range(reintentos):
        try:
            t = yf.Ticker(sym)
            inc, cf, bs = t.income_stmt, t.cashflow, t.balance_sheet
            return {"ingresos": fila(inc, ["Total Revenue", "Operating Revenue"]),
                    "util_op": fila(inc, ["Operating Income", "EBIT"]),
                    "fcf": fila(cf, ["Free Cash Flow"]),
                    "acciones": fila(bs, ["Ordinary Shares Number", "Share Issued"]),
                    "cap_invertido": fila(bs, ["Invested Capital"])}
        except Exception:  # noqa: BLE001
            time.sleep(2 * (intento + 1))
    return {}


def _cagr(serie: list) -> float | None:
    """Crecimiento compuesto entre el dato más viejo y el más reciente (serie: reciente primero)."""
    if len(serie) < 2 or serie[-1] is None or serie[-1] <= 0 or serie[0] is None or serie[0] <= 0:
        return None
    return (serie[0] / serie[-1]) ** (1 / (len(serie) - 1)) - 1


def metricas(inf: dict, est: dict) -> dict:
    ing, uop = est.get("ingresos") or [], est.get("util_op") or []
    margenes = [u / i for u, i in zip(uop, ing) if i]
    roic = None
    if uop and est.get("cap_invertido") and est["cap_invertido"][0] > 0:
        roic = uop[0] * (1 - 0.21) / est["cap_invertido"][0]
    ebitda, deuda, caja = inf.get("ebitda"), inf.get("deuda"), inf.get("caja")
    deuda_neta = (deuda - caja) if deuda is not None and caja is not None else None
    ratio = None
    if deuda_neta is not None and ebitda is not None:
        ratio = (deuda_neta / ebitda) if ebitda > 0 else (0.0 if deuda_neta <= 0 else float("inf"))
    return {"margen_op": inf.get("margen_op"), "roe": inf.get("roe"), "roic": roic,
            "crec_3a": _cagr(ing), "dilucion": _cagr(est.get("acciones") or []),
            "fcf": est.get("fcf") or [], "deuda_ebitda": ratio,
            "estab_margen": (float(np.std(margenes)) if len(margenes) >= 3 else None)}


def capa3(inf: dict, m: dict) -> tuple[bool, list, int]:
    """(pasa, motivos de descarte, n.º de reglas que se pudieron verificar)."""
    fallas, n = [], 0
    financiera = inf.get("sector") == "Financial Services"
    if m["crec_3a"] is not None:
        n += 1
        if m["crec_3a"] < 0:
            fallas.append("ingresos cayendo a 3 años")
    if m["dilucion"] is not None:
        n += 1
        if m["dilucion"] > DILUCION_MAX:
            fallas.append(f"dilución {m['dilucion']:.0%}/año")
    if financiera:   # bancos y aseguradoras: FCF y deuda/EBITDA no aplican
        if m["roe"] is not None:
            n += 1
            if m["roe"] < ROE_MIN_FINANCIERAS:
                fallas.append(f"ROE {m['roe']:.0%} < {ROE_MIN_FINANCIERAS:.0%}")
        return not fallas, fallas, n
    if m["margen_op"] is not None:
        n += 1
        if m["margen_op"] < 0:
            fallas.append("margen operativo negativo")
    if len(m["fcf"]) >= 2:
        n += 1
        if sum(1 for x in m["fcf"][:3] if x < 0) >= 2:
            fallas.append("FCF negativo 2 de 3 años")
    if m["deuda_ebitda"] is not None and inf.get("sector") != "Utilities":
        n += 1
        if m["deuda_ebitda"] > DEUDA_EBITDA_MAX:
            fallas.append("deuda neta/EBITDA > 3.5")
    return not fallas, fallas, n


def especulativa_ok(inf: dict, m: dict, tags: set) -> bool:
    """Cupo aparte para temas sin utilidades: debe estar en un ETF temático y tener caja para 2 años."""
    if not tags & TEMATICOS:
        return False
    if (inf.get("cap") or 0) < CAP_MIN["Especulativa"] or _vol_usd(inf) < VOL_USD_MIN["Especulativa"]:
        return False
    if not ((inf.get("crec_ingresos") or 0) > 0 or (m["crec_3a"] or 0) > 0):
        return False
    fcf = m["fcf"][0] if m["fcf"] else None
    return fcf is None or fcf >= 0 or (inf.get("caja") or 0) >= 2 * abs(fcf)


def _vol_usd(inf: dict) -> float:
    return (inf.get("vol_prom") or 0) * (inf.get("precio") or 0)


def capa1(inf: dict, cat: str) -> bool:
    clave = cat if cat in CAP_MIN else "general"
    if (inf.get("cap") or 0) < CAP_MIN[clave] or _vol_usd(inf) < VOL_USD_MIN[clave]:
        return False
    if (inf.get("precio") or 0) < PRECIO_MIN:
        return False
    if inf.get("primer_dia"):
        anios = (time.time() - inf["primer_dia"]) / (365.25 * 86400)
        if anios < ANIOS_HISTORIA:
            return False
    return True


def capa2(inf: dict, tags: set, sym: str) -> bool:
    if inf.get("pais") == "United States":
        return bool(tags & INDICES_EEUU)
    return bool(tags & INDICES_INTL) or sym in LATAM_EM


def puntaje(filas: list[dict]) -> None:
    """Puntaje 0-100 por percentiles dentro de la categoría (se guarda en f['calidad'])."""
    df = pd.DataFrame([{"rent": f["m"]["roic"] if f["m"]["roic"] is not None else f["m"]["roe"],
                        "estab": -f["m"]["estab_margen"] if f["m"]["estab_margen"] is not None else None,
                        "crec": f["m"]["crec_3a"],
                        "balance": -f["m"]["deuda_ebitda"] if f["m"]["deuda_ebitda"] is not None else None}
                       for f in filas], dtype=float)
    pct = df.rank(pct=True)
    for f, (_, r) in zip(filas, pct.iterrows()):
        vals = [x for x in r.tolist() if not np.isnan(x)]
        f["calidad"] = int(round(100 * sum(vals) / len(vals))) if vals else None


def _descargar_en_paralelo(func, simbolos, cache, clave, hilos):
    pend = [t for t in simbolos if clave not in cache.get(t, {})]
    for i in range(0, len(pend), 40):
        lote = pend[i:i + 40]
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for t, res in zip(lote, ex.map(func, lote)):
                if res:
                    cache.setdefault(t, {})[clave] = res
                    cache[t]["_fecha"] = pd.Timestamp.today().date().isoformat()
        Path(CACHE_FICHAS).parent.mkdir(parents=True, exist_ok=True)
        Path(CACHE_FICHAS).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"   {clave}: {min(i + 40, len(pend))}/{len(pend)}")


def actualizar_universo(hilos=4, ruta=ARCHIVO_UNIVERSO):
    """Descarga UNA vez listas + fichas, aplica el filtro de calidad y escribe src/universo_etfs.py."""
    print("1/5 Listas base (S&P 1500, ETFs internacionales y temáticos)...")
    activos, cobertura = construir_universo(FUENTES_BASE)
    por_sym = {a["ticker"]: a for a in activos}
    for t in LATAM_EM:
        por_sym.setdefault(t, {"ticker": t, "nombre": t, "etfs": "Lista LatAm", "sector_etf": None, "subind_etf": None})
    tags = {t: {x.split()[0] for x in a["etfs"].split(", ")} for t, a in por_sym.items()}

    cache = {}
    if Path(CACHE_FICHAS).exists():
        cache = json.loads(Path(CACHE_FICHAS).read_text(encoding="utf-8"))
        limite = (pd.Timestamp.today() - pd.Timedelta(days=20)).date().isoformat()
        cache = {t: d for t, d in cache.items() if str(d.get("_fecha", "")) >= limite}

    print(f"2/5 Fichas de {len(por_sym)} empresas (capas 1 y 2)...")
    _descargar_en_paralelo(obtener_info, list(por_sym), cache, "info", hilos)
    conteo = {"base": len(por_sym)}
    cand = []
    for t in por_sym:
        inf = cache.get(t, {}).get("info")
        if not inf or inf.get("quote_type") not in (None, "EQUITY") or \
                (inf.get("bolsa") and inf["bolsa"] not in BOLSAS_EEUU_YF):
            continue
        cat = _categoria(inf, tags[t], t)
        tematica = bool(tags[t] & TEMATICOS)
        if cat is None and not tematica:
            continue
        pasa1 = cat is not None and capa1(inf, cat)
        if not pasa1 and not (tematica and capa1(inf, "Especulativa")):
            continue
        cand.append({"t": t, "cat": cat, "tags": tags[t], "pasa1": pasa1,
                     "pasa2": cat is not None and pasa1 and capa2(inf, tags[t], t)})
    conteo["capa1"] = sum(c["pasa1"] for c in cand)
    conteo["capa2"] = sum(c["pasa2"] for c in cand)

    print(f"3/5 Estados financieros de {len(cand)} candidatas (capas 3 y 4)...")
    _descargar_en_paralelo(obtener_estados, [c["t"] for c in cand], cache, "estados", hilos)
    calidad, especulativas = [], []
    for c in cand:
        inf = cache[c["t"]]["info"]
        m = metricas(inf, cache[c["t"]].get("estados") or {})
        ok3, fallas, n = capa3(inf, m) if c["pasa2"] else (False, ["fuera de índice"], 0)
        c.update(m=m, fallas=fallas)
        if c["pasa2"] and ok3 and n > 0:
            c["etiqueta"] = "Calidad" if n >= 3 else "Datos parciales"
            calidad.append(c)
        elif c["cat"] in (None, "Tierras raras y minería", "Tecnología", "Sectoriales") and \
                especulativa_ok(inf, m, c["tags"]):
            c["etiqueta"], c["cat"] = "Especulativa", c["cat"] or "Especulativa"
            especulativas.append(c)
    conteo["capa3"] = len(calidad)

    elegidas = []
    for cat in sorted({c["cat"] for c in calidad}):
        grupo = [c for c in calidad if c["cat"] == cat]
        puntaje(grupo)
        grupo.sort(key=lambda c: -(c["calidad"] if c["calidad"] is not None else -1))
        tramo = TRAMO.get(cat, TRAMO["general"])
        n_quedan = len(grupo) if len(grupo) <= 4 else max(1, int(np.ceil(len(grupo) * tramo)))
        elegidas += grupo[:n_quedan]
    conteo["capa4"] = len(elegidas)
    especulativas.sort(key=lambda c: -(cache[c["t"]]["info"].get("cap") or 0))
    especulativas = [c for c in especulativas if c["t"] not in {e["t"] for e in elegidas}][:MAX_ESPECULATIVAS]
    for c in especulativas:
        c["calidad"] = None
    conteo["especulativas"] = len(especulativas)

    finales = elegidas + especulativas
    print(f"4/5 Descripciones en español de {len(finales)} empresas...")
    sin_desc = {c["t"]: cache[c["t"]]["info"] for c in finales
                if cache[c["t"]]["info"].get("resumen") and not cache[c["t"]].get("desc_es")}
    if sin_desc:
        for t, d in describir(sin_desc).items():
            cache[t]["desc_es"] = d
        Path(CACHE_FICHAS).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    universo = {}
    for c in sorted(finales, key=lambda c: (c["cat"], -(c["calidad"] or 0))):
        inf = cache[c["t"]]["info"]
        f = _ficha(por_sym[c["t"]], inf, cache[c["t"]].get("desc_es"))
        f.update(categoria=c["cat"], etiqueta=c["etiqueta"], calidad=c["calidad"],
                 riesgo="China: riesgo regulatorio/ADR" if inf.get("pais") in ("China", "Hong Kong") else "")
        universo[c["t"]] = f

    resumen = pd.Series([c["cat"] for c in finales]).value_counts().to_dict() if finales else {}
    hoy = pd.Timestamp.today().date()
    texto = (f'"""Universo fijo del Reporte 2 — generado por tools/actualizar_universo_etfs.py el {hoy}.\n'
             "Acciones de calidad (y un cupo especulativo) que cotizan en bolsa de EE.UU. Puedes corregir\n"
             'descripciones a mano; se sobrescribe la próxima vez que se actualice el universo."""\n\n'
             f"FECHA_UNIVERSO = {str(hoy)!r}\n\n"
             f"FILTRO = {pprint.pformat({'conteo': conteo, 'por_categoria': resumen}, width=110, sort_dicts=False)}\n\n"
             f"COBERTURA = {pprint.pformat(cobertura.to_dict('records'), width=110, sort_dicts=False)}\n\n"
             f"UNIVERSO = {pprint.pformat(universo, width=110, sort_dicts=False)}\n")
    Path(ruta).write_text(texto, encoding="utf-8")
    print(f"5/5 Escrito {ruta}")
    print("   Embudo:", " -> ".join(f"{k} {v}" for k, v in conteo.items()))
    print("   Por categoría:", resumen)
    return universo


if __name__ == "__main__":
    # En Windows la consola puede no aceptar UTF-8 (✔ ⚠)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    actualizar_universo()
