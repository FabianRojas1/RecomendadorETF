"""
gatillo.py - Seguimiento de las señales MP de semanas previas (compra y venta).

ENTRAR AHORA y SALIR son estados pasajeros: si la entrada funciona, el precio se
aleja del soporte y ENTRAR AHORA desaparece; si el precio corrige, deja de estar
extendido y SALIR desaparece. Por eso la confirmacion NO se mide repitiendo el
estado, sino por lo que hizo el precio despues de la señal.

Se reevalua el MP sobre las 3 velas semanales cerradas anteriores (misma logica de
signals.evaluar_mp, con la fecha de corte de cada semana) y se compara contra el
cierre semanal de hoy.

COMPRA (solo si el LP sigue permitiendo comprar)
  CONFIRMADO : hubo ENTRAR AHORA en las 3 semanas previas y el cierre de hoy esta
               por encima del cierre de esa semana. Si el precio ya esta extendido
               (> 2 ATR sobre la EMA10 semanal) no se muestra: ya no es una entrada.
  NUEVO      : ENTRAR AHORA esta semana, sin confirmacion todavia.
  (No se reporta el gatillo que no se sostuvo.)

VENTA (solo posiciones abiertas)
  ESTRUCTURAL   : SALIR hoy por cierre bajo EMA55 semanal o stop de tesis. No se espera.
  NUEVA         : SALIR hoy por toma de ganancia (extension, techo de SQZ, divergencia).
  CONFIRMADA    : hubo SALIR en las 3 semanas previas y el cierre de hoy esta por debajo
                  del cierre de esa semana.
  NO CONFIRMADA : hubo SALIR pero el precio siguio subiendo.

No usa memoria: se reconstruye desde el precio, asi que funciona desde la primera corrida.
"""
import logging
from datetime import date, timedelta

import pandas as pd

from src import signals as lp_mp
from src.indicators import IndicatorCalculator

logger = logging.getLogger(__name__)

SEMANAS = 3
ENTRAR = "ENTRAR AHORA"
SALIR = "SALIR"


def _num(x):
    try:
        x = float(x)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _ultimo_cierre_semanal(df: pd.DataFrame, hoy: date):
    """Etiqueta (domingo) de la ultima vela semanal cerrada a la fecha `hoy`."""
    etiquetas = df.resample("W").last().dropna(how="all").index
    cerradas = [e for e in etiquetas if pd.Timestamp(e).date() <= hoy]
    return pd.Timestamp(cerradas[-1]) if cerradas else None


def historial(df: pd.DataFrame, semanas: int = SEMANAS, hoy: date = None) -> list:
    """
    MP de cada una de las `semanas` velas semanales anteriores a la ultima cerrada,
    de la mas reciente a la mas antigua: [{"semana", "estado", "cierre", "estructural"}].
    "semana" es el lunes de esa vela, como la rotula TradingView.
    """
    hoy = hoy or date.today()
    ultimo = _ultimo_cierre_semanal(df, hoy)
    if ultimo is None:
        return []
    idx = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
    salida = []
    for k in range(1, semanas + 1):
        corte = ultimo - pd.Timedelta(days=7 * k)
        fila = {"semana": corte.date() - timedelta(days=6), "estado": "SIN DATOS",
                "cierre": None, "estructural": False}
        try:
            calc = IndicatorCalculator(df[idx <= corte], asof=corte.date())
            v = calc.valores_lp()
            v.update(calc.valores_mp())
            mp = lp_mp.evaluar_mp(v)
            ventas = mp.get("ventas") or {}
            fila.update(estado=mp.get("estado", "SIN DATOS"), cierre=_num(v.get("sem_close")),
                        estructural=bool(ventas.get("trailing_ema55") or ventas.get("stop_tesis")))
        except Exception as e:  # noqa: BLE001  (historia corta, etc.)
            logger.debug("Señal previa %s: %s", corte.date(), e)
        salida.append(fila)
    return salida


def _var(hoy_c, previo_c):
    return (hoy_c / previo_c - 1) * 100 if hoy_c and previo_c else None


def _sem(d: date) -> str:
    return d.strftime("%d/%m")


def senal_compra(mp_hoy: dict, v_hoy: dict, previas: list):
    """CONFIRMADO / NUEVO, o None si no hay nada que mostrar."""
    cierre = _num(v_hoy.get("sem_close"))
    e10, atr = _num(v_hoy.get("sem_ema10")), _num(v_hoy.get("sem_atr"))
    extendido = bool(cierre and e10 and atr and cierre > e10 + lp_mp.EXTENSION_ATR_MULT * atr)

    previa = next((p for p in previas if p["estado"] == ENTRAR and p["cierre"]), None)
    if previa and cierre and cierre > previa["cierre"]:
        if extendido:
            return None   # ya subio demasiado: no perseguir, no se muestra
        var = _var(cierre, previa["cierre"])
        return {"estado": "CONFIRMADO", "semana": previa["semana"].isoformat(),
                "precio_senal": previa["cierre"], "var_pct": var,
                "texto": f"Confirmado {var:+.1f}% (sem. {_sem(previa['semana'])})"}
    if mp_hoy.get("estado") == ENTRAR:
        return {"estado": "NUEVO", "semana": None, "precio_senal": cierre, "var_pct": None,
                "texto": "Nuevo, sin confirmar"}
    return None


def senal_venta(mp_hoy: dict, v_hoy: dict, previas: list):
    """ESTRUCTURAL / NUEVA / CONFIRMADA / NO CONFIRMADA, o None."""
    if mp_hoy.get("estado") == SALIR:
        ventas = mp_hoy.get("ventas") or {}
        if ventas.get("trailing_ema55") or ventas.get("stop_tesis"):
            return {"estado": "ESTRUCTURAL", "semana": None, "var_pct": None,
                    "texto": "Estructural: no esperar"}
        return {"estado": "NUEVA", "semana": None, "var_pct": None, "texto": "Nueva, sin confirmar"}

    cierre = _num(v_hoy.get("sem_close"))
    previa = next((p for p in previas if p["estado"] == SALIR and p["cierre"]), None)
    if previa and cierre:
        var = _var(cierre, previa["cierre"])
        if cierre < previa["cierre"]:
            return {"estado": "CONFIRMADA", "semana": previa["semana"].isoformat(), "var_pct": var,
                    "texto": f"Confirmada {var:+.1f}% (sem. {_sem(previa['semana'])})"}
        return {"estado": "NO CONFIRMADA", "semana": previa["semana"].isoformat(), "var_pct": var,
                "texto": f"No confirmada {var:+.1f}% (sem. {_sem(previa['semana'])})"}
    return None


def evaluar(df: pd.DataFrame, v_hoy: dict, lp_hoy: dict, mp_hoy: dict,
            tiene_posicion: bool = False, hoy: date = None) -> dict:
    """
    {"compra": ..., "venta": ...}. Solo reconstruye las semanas previas cuando hace falta:
    compra si el LP permite comprar; venta si hay posicion abierta.
    """
    ver_compra = lp_mp.lp_puede_comprar(lp_hoy)
    ver_venta = bool(tiene_posicion)
    if not (ver_compra or ver_venta):
        return {"compra": None, "venta": None}
    previas = historial(df, hoy=hoy)
    return {"compra": senal_compra(mp_hoy, v_hoy, previas) if ver_compra else None,
            "venta": senal_venta(mp_hoy, v_hoy, previas) if ver_venta else None}
