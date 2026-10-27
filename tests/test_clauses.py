"""Tests del ranking de cláusulas abiertas (rendimiento por millón de cláusula)."""

import math

import pandas as pd
import pytest

from fantasy.analytics.clauses import CRITERIOS, enriquecer_clausulas, ranking_clausulas


def squad():
    return pd.DataFrame([
        # Titular caro y bueno.
        {"player_id": "1", "player_name": "Crack", "points": 80, "average_points": 8.0,
         "market_value": 40_000_000, "buyout_clause": 50_000_000},
        # Titular barato: el chollo de verdad.
        {"player_id": "2", "player_name": "Chollo", "points": 40, "average_points": 5.0,
         "market_value": 4_000_000, "buyout_clause": 5_000_000},
        # Suplente baratísimo: pts/M€ altísimo, pero no juega.
        {"player_id": "3", "player_name": "Suplente", "points": 15, "average_points": 3.0,
         "market_value": 300_000, "buyout_clause": 300_000},
        # Sin cláusula informada.
        {"player_id": "4", "player_name": "SinDato", "points": 10, "average_points": 2.0,
         "market_value": 1_000_000, "buyout_clause": None},
    ])


def gw():
    filas = []
    for j in range(1, 8):
        filas.append({"player_id": "1", "gameweek": j, "points": 8, "minutes": 90})
        filas.append({"player_id": "2", "gameweek": j, "points": 6, "minutes": 85})
        # El suplente solo juega 10 minutos, y solo en la última jornada.
        if j == 7:
            filas.append({"player_id": "3", "gameweek": j, "points": 2, "minutes": 10})
    return pd.DataFrame(filas)


def test_rendimiento_se_calcula_sobre_la_clausula_no_sobre_el_valor():
    df = enriquecer_clausulas(squad(), gw()).set_index("player_id")
    assert df.loc["1", "pts_por_millon"] == pytest.approx(80 / 50)
    assert df.loc["2", "pts_por_millon"] == pytest.approx(40 / 5)
    assert df.loc["2", "sobrecoste"] == 1_000_000
    # Ventana de 5 jornadas (3..7): 5 x 6 = 30 puntos, 5 x 85 minutos.
    assert df.loc["2", "forma"] == 30
    assert df.loc["2", "pct_minutos"] == pytest.approx(5 * 85 / 450 * 100)
    assert df.loc["2", "forma_por_millon"] == pytest.approx(30 / 5)
    # Sin cláusula no hay división posible: NaN, no infinito ni cero.
    assert math.isnan(df.loc["4", "pts_por_millon"])


def test_quien_no_aparece_en_la_ventana_tiene_forma_cero():
    df = enriquecer_clausulas(squad(), gw()).set_index("player_id")
    assert df.loc["4", "forma"] == 0
    assert df.loc["4", "pct_minutos"] == 0


def test_el_filtro_de_regularidad_saca_al_suplente_barato():
    df = enriquecer_clausulas(squad(), gw())

    sin_filtro = ranking_clausulas(df, "pts_millon", solo_juegan=False)
    assert sin_filtro["player_name"].iloc[0] == "Suplente"  # 15 / 0,3 = 50 pts/M€

    con_filtro = ranking_clausulas(df, "pts_millon", solo_juegan=True)
    assert list(con_filtro["player_name"]) == ["Chollo", "Crack"]


def test_presupuesto_maximo():
    df = enriquecer_clausulas(squad(), gw())
    out = ranking_clausulas(df, "puntos", solo_juegan=False, clausula_max=10_000_000)
    assert "Crack" not in set(out["player_name"])
    assert "SinDato" not in set(out["player_name"])


@pytest.mark.parametrize("criterio", sorted(CRITERIOS))
def test_todos_los_criterios_ordenan_sin_errores(criterio):
    df = enriquecer_clausulas(squad(), gw())
    out = ranking_clausulas(df, criterio, solo_juegan=False)
    assert len(out) == 4


def test_sin_estadisticas_por_jornada_no_filtra_ni_inventa_ceros():
    df = enriquecer_clausulas(squad(), pd.DataFrame())
    assert df["forma"].isna().all()
    assert df["pct_minutos"].isna().all()
    # Sin datos de minutos el filtro no puede decidir: no vacía la tabla.
    assert len(ranking_clausulas(df, "pts_millon", solo_juegan=True)) == 4
