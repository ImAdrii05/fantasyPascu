"""Tests unitarios para los módulos de analítica y tendencias de mercado."""

import pandas as pd
import pytest

from fantasy.analytics.bargains import (
    calculate_price_trends,
    get_top_risers,
    get_top_fallers,
)


def test_calculate_price_trends_multi_day():
    df_daily = pd.DataFrame([
        {"snapshot_date": "2026-09-01", "player_id": "1", "market_value": 1000000},
        {"snapshot_date": "2026-09-02", "player_id": "1", "market_value": 1100000}, # +10%
        {"snapshot_date": "2026-09-01", "player_id": "2", "market_value": 2000000},
        {"snapshot_date": "2026-09-02", "player_id": "2", "market_value": 1900000}, # -5%
    ])

    trends = calculate_price_trends(df_daily, days_window=1)
    assert len(trends) == 2

    p1 = trends[trends["player_id"] == "1"].iloc[0]
    assert p1["current_value"] == 1100000
    assert p1["prev_value"] == 1000000
    assert p1["diff_value"] == 100000
    assert p1["pct_change"] == pytest.approx(10.0)

    p2 = trends[trends["player_id"] == "2"].iloc[0]
    assert p2["current_value"] == 1900000
    assert p2["diff_value"] == -100000
    assert p2["pct_change"] == pytest.approx(-5.0)


def test_calculate_price_trends_single_day():
    df_daily = pd.DataFrame([
        {"snapshot_date": "2026-09-01", "player_id": "1", "market_value": 1000000},
    ])
    trends = calculate_price_trends(df_daily, days_window=1)
    assert len(trends) == 1
    assert trends.iloc[0]["current_value"] == 1000000
    assert trends.iloc[0]["pct_change"] is None


def test_get_top_risers_and_fallers():
    df_market = pd.DataFrame([
        {"name": "Jugador A", "pct_change": 12.5, "diff_value": 50000},
        {"name": "Jugador B", "pct_change": 3.2, "diff_value": 100000},
        {"name": "Jugador C", "pct_change": -4.0, "diff_value": -20000},
    ])

    risers = get_top_risers(df_market, top_n=2)
    assert len(risers) == 2
    assert risers.iloc[0]["name"] == "Jugador A"
    assert risers.iloc[1]["name"] == "Jugador B"

    fallers = get_top_fallers(df_market, top_n=1)
    assert len(fallers) == 1
    assert fallers.iloc[0]["name"] == "Jugador C"
