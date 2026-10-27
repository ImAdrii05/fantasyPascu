"""Tests de la selección de ligas del job diario (sin red ni Supabase)."""

import pytest

from fantasy import config
from fantasy.api.models import League
from fantasy.collect.run_daily import resolve_leagues


class FakeClient:
    def __init__(self, leagues=None, error=None):
        self._leagues = leagues or []
        self._error = error

    def get_user_leagues(self):
        if self._error:
            raise self._error
        return self._leagues, [league.to_dict() for league in self._leagues]


class FakeStore:
    def __init__(self, fail_upsert=False):
        self.raw = []
        self.saved_leagues = None
        self.fail_upsert = fail_upsert

    def save_raw_snapshot(self, endpoint, payload, snapshot_date=None):
        self.raw.append(endpoint)

    def upsert_leagues(self, leagues):
        if self.fail_upsert:
            raise RuntimeError('relation "leagues" does not exist')
        self.saved_leagues = leagues
        return len(leagues)


CUENTA = [League(id="1", name="Liga Curro"), League(id="2", name="Liga Familia")]


def test_sin_league_id_recolecta_todas_las_de_la_cuenta(monkeypatch):
    monkeypatch.setattr(config, "FANTASY_LEAGUE_ID", "")
    store, errors = FakeStore(), []

    leagues = resolve_leagues(FakeClient(CUENTA), store, errors)

    assert [lg.id for lg in leagues] == ["1", "2"]
    assert store.saved_leagues == leagues
    assert store.raw == ["user_leagues"]
    assert errors == []


def test_league_id_fijado_limita_y_conserva_nombres(monkeypatch):
    monkeypatch.setattr(config, "FANTASY_LEAGUE_ID", " 2 , 99 ")

    leagues = resolve_leagues(FakeClient(CUENTA), FakeStore(), [])

    # La 2 trae su nombre real; la 99 no está en la cuenta pero se pidió explícitamente.
    assert [(lg.id, lg.name) for lg in leagues] == [("2", "Liga Familia"), ("99", "Liga 99")]


@pytest.mark.parametrize("fixed, expected", [("5", ["5"]), ("", [])])
def test_fallo_al_pedir_ligas(monkeypatch, fixed, expected):
    monkeypatch.setattr(config, "FANTASY_LEAGUE_ID", fixed)
    errors = []

    leagues = resolve_leagues(FakeClient(error=RuntimeError("HTTP 500")), FakeStore(), errors)

    assert [lg.id for lg in leagues] == expected
    assert len(errors) == 1 and "HTTP 500" in errors[0]


def test_sin_tabla_leagues_no_impide_recolectar(monkeypatch):
    monkeypatch.setattr(config, "FANTASY_LEAGUE_ID", "")
    errors = []

    leagues = resolve_leagues(FakeClient(CUENTA), FakeStore(fail_upsert=True), errors)

    assert [lg.id for lg in leagues] == ["1", "2"]
    assert errors == []
