"""Tests del job diario: selección de ligas y cuándo recolectar (sin red ni Supabase)."""

from datetime import datetime, timezone

import pytest

from fantasy import config
from fantasy.api.models import League, Player
from fantasy.collect.run_daily import (
    MARCA_DIA_COMPLETO,
    decidir_recoleccion,
    mercado_actualizado,
    resolve_leagues,
)


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


# --- Decisión de recolectar: día completo, mercado sin recalcular, hora límite ---


class StoreDia:
    def __init__(self, completos=(), anteriores=None):
        self.completos = set(completos)
        self.anteriores = anteriores or {}

    def has_raw_snapshot(self, endpoint, fecha):
        return (endpoint, fecha) in self.completos

    def get_previous_market_values(self, fecha):
        return self.anteriores


class ApiJugadores:
    def __init__(self, valores):
        self.valores = valores
        self.llamadas = 0

    def get_all_players(self):
        self.llamadas += 1
        return [Player(id=pid, name=pid, market_value=v) for pid, v in self.valores.items()], None


AYER = {str(i): 1_000_000 + i for i in range(200)}
HOY_RECALCULADO = {pid: v + (5_000 if int(pid) % 3 == 0 else 0) for pid, v in AYER.items()}
MADRUGADA = datetime(2026, 10, 30, 0, 40, tzinfo=timezone.utc)  # la hora no importa, solo .hour
MANANA = datetime(2026, 10, 30, 9, 15, tzinfo=timezone.utc)


def test_mercado_actualizado():
    assert mercado_actualizado(HOY_RECALCULADO, AYER)
    assert not mercado_actualizado(dict(AYER), AYER)
    # Sin referencia (primer día) no se puede saber: se da por bueno.
    assert mercado_actualizado(AYER, {})
    # Valores nulos no cuentan ni a favor ni en contra.
    assert not mercado_actualizado({**AYER, "x": None}, {**AYER, "x": 5})


def test_dia_ya_completo_no_repite_ni_llama_a_la_api():
    api = ApiJugadores(HOY_RECALCULADO)
    recolectar, motivo = decidir_recoleccion(
        StoreDia(completos={(MARCA_DIA_COMPLETO, "2026-10-30")}, anteriores=AYER), api, "2026-10-30", MADRUGADA
    )
    assert not recolectar and "completo" in motivo
    assert api.llamadas == 0


def test_de_madrugada_espera_si_el_mercado_no_ha_cambiado():
    recolectar, motivo = decidir_recoleccion(StoreDia(anteriores=AYER), ApiJugadores(dict(AYER)), "2026-10-30", MADRUGADA)
    assert not recolectar and "recalculado" in motivo


def test_de_madrugada_recolecta_si_el_mercado_ya_cambio():
    recolectar, _ = decidir_recoleccion(StoreDia(anteriores=AYER), ApiJugadores(HOY_RECALCULADO), "2026-10-30", MADRUGADA)
    assert recolectar


def test_pasada_la_hora_limite_recolecta_aunque_no_cambie_nada():
    api = ApiJugadores(dict(AYER))
    recolectar, _ = decidir_recoleccion(StoreDia(anteriores=AYER), api, "2026-10-30", MANANA)
    assert recolectar
    assert api.llamadas == 0


def test_forzar_recolecta_aunque_el_dia_este_completo():
    store = StoreDia(completos={(MARCA_DIA_COMPLETO, "2026-10-30")}, anteriores=AYER)
    recolectar, _ = decidir_recoleccion(store, ApiJugadores(dict(AYER)), "2026-10-30", MADRUGADA, forzar=True)
    assert recolectar


def test_el_dia_del_snapshot_es_el_de_espana():
    # 23:40 UTC del 29 son las 00:40 del 30 en Madrid (horario de invierno)...
    assert config.hoy_juego(datetime(2026, 10, 29, 23, 40, tzinfo=timezone.utc)).isoformat() == "2026-10-30"
    # ...y en verano, 22:40 UTC ya es el día siguiente.
    assert config.hoy_juego(datetime(2026, 7, 1, 22, 40, tzinfo=timezone.utc)).isoformat() == "2026-07-02"
    assert config.ahora_juego(datetime(2026, 10, 29, 23, 40, tzinfo=timezone.utc)).hour == 0
