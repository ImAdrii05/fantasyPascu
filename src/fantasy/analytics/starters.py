"""Estimación de probabilidad de titularidad y minutos esperados.

NOTA DE DISEÑO:
1. Proxy estadístico inmediato: Minutos jugados en las últimas jornadas (>60 min en 3/4 partidos).
2. Evolución prevista (Recomendada): Enlazar y contrastar fuentes curadas por humanos
   expertos (futbolfantasy.com, Jornada Perfecta, Analítica Fantasy) que incorporan
   información cualitativa crítica (ruedas de prensa, rotaciones por competición europea,
   recidivas de lesiones leves) en lugar de intentar entrenar un modelo predictivo cerrado.

Este módulo define las firmas para integrar ambas capas sobre la base de datos.
"""

from typing import Any
import pandas as pd


def estimate_starter_probability_by_minutes(
    df_gameweeks: pd.DataFrame,
    recent_weeks: int = 4,
) -> pd.DataFrame:
    """Calcula la probabilidad de titularidad usando la regularidad de minutos recientes como proxy simple.

    Args:
        df_gameweeks: DataFrame con columnas ['player_id', 'gameweek', 'minutes'].
        recent_weeks: Número de jornadas hacia atrás a evaluar.

    Returns:
        DataFrame indexado por player_id con columnas:
        - 'avg_minutes_recent': Media de minutos en las últimas N jornadas.
        - 'starts_recent': Número de titularidades estimadas (>=60 min).
        - 'starter_confidence': Score entre 0.0 y 1.0.
    """
    if df_gameweeks.empty:
        return pd.DataFrame(columns=["player_id", "avg_minutes_recent", "starts_recent", "starter_confidence"])

    # Placeholder para cálculo una vez que se acumulen datos en player_gameweek_stats
    return pd.DataFrame()
