"""Ranking de cláusulas abiertas: qué jugador rinde más por lo que costaría ficharlo.

Lo que se paga en un clausulazo es la CLÁUSULA, no el valor de mercado, así que toda
relación precio/rendimiento se calcula sobre ella. Un jugador barato de mercado con la
cláusula disparada no es un chollo.

Puntos por millón, sin más, premia a suplentes de 0,3 M con un par de apariciones: la
división se dispara aunque no jueguen. Por eso el ranking va con un filtro de
regularidad (minutos en las últimas jornadas) activo por defecto.
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

# Jornadas que cuentan como "forma reciente" y para medir la regularidad.
VENTANA_FORMA = 5
# Porcentaje de minutos (sobre 90 por jornada de la ventana) para contar como "juega".
MIN_PCT_MINUTOS = 50.0


@dataclass(frozen=True)
class Criterio:
    etiqueta: str
    columna: str
    ascendente: bool
    explicacion: str


CRITERIOS: dict[str, Criterio] = {
    "pts_millon": Criterio(
        "Puntos por millón", "pts_por_millon", False,
        "puntos de la temporada por cada millón de cláusula",
    ),
    "forma_millon": Criterio(
        "Forma por millón", "forma_por_millon", False,
        f"puntos de las últimas {VENTANA_FORMA} jornadas por cada millón de cláusula",
    ),
    "forma": Criterio(
        f"Forma ({VENTANA_FORMA} jornadas)", "forma", False,
        f"puntos sumados en las últimas {VENTANA_FORMA} jornadas",
    ),
    "puntos": Criterio("Puntos totales", "points", False, "puntos de la temporada"),
    "media": Criterio("Media por partido", "average_points", False, "media de puntos por partido"),
    "sobrecoste": Criterio(
        "Menor sobrecoste", "sobrecoste", True,
        "lo que pagarías de más sobre su valor de mercado",
    ),
    "barata": Criterio("Cláusula más barata", "buyout_clause", True, "importe de la cláusula"),
}


# Solo tiene sentido para las que aún no se han abierto, así que va aparte.
APERTURA = Criterio("Se abre antes", "clause_locked_until", True, "hora de apertura, de la más cercana a la más lejana")
TODOS_CRITERIOS: dict[str, Criterio] = {"apertura": APERTURA, **CRITERIOS}


def proximas_a_abrirse(df: pd.DataFrame, ahora: datetime, horas: float | None = None) -> pd.DataFrame:
    """Cláusulas todavía bloqueadas que se abren dentro de `horas` (o todas si es None).

    Los blindados quedan fuera: el escudo bloquea aunque pase la hora de apertura,
    así que esa hora no dice cuándo se podrá pagar.
    """
    apertura = pd.to_datetime(df["clause_locked_until"], utc=True, errors="coerce")
    blindado = df["is_shielded"].fillna(False).astype(bool) if "is_shielded" in df else False
    mascara = apertura.notna() & (apertura > ahora) & ~blindado
    if horas is not None:
        mascara &= apertura <= ahora + pd.Timedelta(hours=horas)
    out = df[mascara].copy()
    out["clause_locked_until"] = apertura[mascara]
    return out.sort_values("clause_locked_until")


def enriquecer_clausulas(df_squad: pd.DataFrame, df_gw: pd.DataFrame, ventana: int = VENTANA_FORMA) -> pd.DataFrame:
    """Añade forma, regularidad y rendimiento por millón de cláusula a cada jugador.

    Columnas nuevas: `sobrecoste`, `pts_por_millon`, `forma`, `forma_por_millon` y
    `pct_minutos`. Sin estadísticas por jornada, forma y minutos quedan en NaN (no hay
    dato), no en cero: un cero diría que no juega, y eso no lo sabemos.

    Args:
        df_squad: Jugadores de las plantillas (`player_id`, `points`, `market_value`,
            `buyout_clause`...).
        df_gw: Estadísticas por jornada (`player_id`, `gameweek`, `points`, `minutes`).
        ventana: Últimas jornadas que cuentan para la forma y los minutos.
    """
    df = df_squad.copy()
    millones = pd.to_numeric(df["buyout_clause"], errors="coerce") / 1_000_000
    millones = millones.where(millones > 0)

    df["sobrecoste"] = pd.to_numeric(df["buyout_clause"], errors="coerce") - pd.to_numeric(
        df["market_value"], errors="coerce"
    )
    df["pts_por_millon"] = pd.to_numeric(df["points"], errors="coerce") / millones

    if df_gw is None or df_gw.empty:
        df["forma"] = float("nan")
        df["pct_minutos"] = float("nan")
    else:
        ultima = int(df_gw["gameweek"].max())
        reciente = df_gw[df_gw["gameweek"] > ultima - ventana]
        resumen = reciente.groupby(reciente["player_id"].astype(str)).agg(
            forma=("points", "sum"), minutos=("minutes", "sum")
        )
        ids = df["player_id"].astype(str)
        # Quien no aparece en la ventana no ha jugado: ahí el cero sí es un dato.
        df["forma"] = ids.map(resumen["forma"]).fillna(0)
        minutos = ids.map(resumen["minutos"]).fillna(0)
        df["pct_minutos"] = (minutos / (ventana * 90) * 100).clip(upper=100)

    df["forma_por_millon"] = df["forma"] / millones
    return df


def ranking_clausulas(
    df: pd.DataFrame,
    criterio: str,
    solo_juegan: bool = True,
    clausula_max: int | None = None,
) -> pd.DataFrame:
    """Ordena las cláusulas según el criterio, con los filtros de regularidad y presupuesto.

    `solo_juegan` deja fuera a quien no llega a MIN_PCT_MINUTOS en la ventana. Si no
    hay datos de minutos, no filtra: dejar la tabla vacía por falta de datos sería
    peor que no filtrar.
    """
    c = TODOS_CRITERIOS[criterio]
    out = df
    if solo_juegan and out["pct_minutos"].notna().any():
        out = out[out["pct_minutos"] >= MIN_PCT_MINUTOS]
    if clausula_max is not None:
        out = out[pd.to_numeric(out["buyout_clause"], errors="coerce") <= clausula_max]
    return out.sort_values(c.columna, ascending=c.ascendente, na_position="last")
