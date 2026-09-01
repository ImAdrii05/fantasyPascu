"""Cálculo y ranking de chollos y tendencias de mercado."""

import pandas as pd


def calculate_price_trends(df_daily: pd.DataFrame, days_window: int = 1) -> pd.DataFrame:
    """Calcula el incremento absoluto y porcentual de valor de mercado en una ventana temporal.

    Args:
        df_daily: DataFrame con columnas ['snapshot_date', 'player_id', 'market_value'].
        days_window: Número de snapshots hacia atrás a comparar (1 = snapshot inmediatamente anterior).

    Returns:
        DataFrame con columnas ['player_id', 'current_value', 'prev_value', 'diff_value', 'pct_change'].
    """
    if df_daily.empty or "snapshot_date" not in df_daily.columns or "market_value" not in df_daily.columns:
        return pd.DataFrame(columns=["player_id", "current_value", "prev_value", "diff_value", "pct_change"])

    df = df_daily.copy()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    dates = sorted(df["snapshot_date"].unique())
    if not dates:
        return pd.DataFrame(columns=["player_id", "current_value", "prev_value", "diff_value", "pct_change"])

    latest_date = dates[-1]
    df_latest = df[df["snapshot_date"] == latest_date][["player_id", "market_value"]].copy()
    df_latest.rename(columns={"market_value": "current_value"}, inplace=True)

    if len(dates) < 2:
        df_latest["prev_value"] = None
        df_latest["diff_value"] = None
        df_latest["pct_change"] = None
        return df_latest

    prev_idx = max(0, len(dates) - 1 - days_window)
    prev_date = dates[prev_idx]

    df_prev = df[df["snapshot_date"] == prev_date][["player_id", "market_value"]].copy()
    df_prev.rename(columns={"market_value": "prev_value"}, inplace=True)

    merged = pd.merge(df_latest, df_prev, on="player_id", how="left")
    merged["diff_value"] = merged["current_value"] - merged["prev_value"]
    # Evitar división por cero
    merged["pct_change"] = merged.apply(
        lambda r: (r["diff_value"] / r["prev_value"] * 100.0)
        if pd.notnull(r["prev_value"]) and r["prev_value"] > 0
        else None,
        axis=1,
    )
    return merged


def get_top_risers(df_market: pd.DataFrame, top_n: int = 50, only_positive: bool = False) -> pd.DataFrame:
    """Devuelve los jugadores ordenados por mayor subida porcentual (pct_change).

    Args:
        df_market: DataFrame de jugadores con columna 'pct_change'.
        top_n: Límite de jugadores a devolver.
        only_positive: Si True, filtra solo aquellos con subida estrictamente positiva (> 0).

    Returns:
        DataFrame ordenado de forma descendente por pct_change.
    """
    if df_market.empty or "pct_change" not in df_market.columns:
        return df_market
    df = df_market.copy()
    if only_positive:
        df = df[df["pct_change"] > 0]
    return df.sort_values(by="pct_change", ascending=False).head(top_n)


def get_top_fallers(df_market: pd.DataFrame, top_n: int = 50, only_negative: bool = False) -> pd.DataFrame:
    """Devuelve los jugadores ordenados por mayor caída porcentual (pct_change ascendente)."""
    if df_market.empty or "pct_change" not in df_market.columns:
        return df_market
    df = df_market.copy()
    if only_negative:
        df = df[df["pct_change"] < 0]
    return df.sort_values(by="pct_change", ascending=True).head(top_n)


def get_bargain_ranking(
    df_players: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_gameweeks: pd.DataFrame | None = None,
    min_points_avg: float = 3.0,
    max_price: int | None = None,
    top_n: int = 25,
) -> pd.DataFrame:
    """Genera el ranking de chollos combinando rendimiento, precio y tendencia alcista."""
    if df_daily.empty or df_players.empty:
        return pd.DataFrame(columns=["player_name", "team", "position", "market_value", "bargain_score"])

    # Estructura preparada para el cálculo final con histórico acumulado
    return pd.DataFrame()
