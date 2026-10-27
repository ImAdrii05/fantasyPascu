"""Tests unitarios para los modelos y cliente de la API de LaLiga Fantasy."""

from datetime import datetime, timedelta, timezone

import responses
import pytest

from fantasy.api import FantasyApiClient, FantasyApiError
from fantasy.api.models import Team, Player, League, LeagueStanding, LeagueMovement, PlayerGameweekStat, SquadPlayer
from fantasy.collect.players import extract_gameweek_stats
from fantasy.collect.player_details import parse_player_detail
from fantasy.auth.store import BaseTokenStore, set_token_store
from fantasy.auth.tokens import TokenSet


class DummyTokenStore(BaseTokenStore):
    def load(self):
        return TokenSet(access_token="test_bearer_token", expires_at=9999999999)
    def save(self, tokens):
        pass


def setup_module():
    set_token_store(DummyTokenStore())


def test_team_from_api_tolerant():
    data = {
        "id": "19",
        "name": "Real Madrid",
        "shortName": "RMA",
        "slug": "real-madrid",
        "badgeColor": "https://assets.laliga.com/rma.png",
        "extraField": "ignored",
    }
    team = Team.from_api(data)
    assert team.id == "19"
    assert team.name == "Real Madrid"
    assert team.short_name == "RMA"
    assert team.slug == "real-madrid"
    assert team.badge_url == "https://assets.laliga.com/rma.png"


def test_player_from_api_tolerant_nulls():
    # Campos faltantes deben ser None, nunca 0
    data = {
        "id": "1001",
        "name": "Vinicius Jr",
        "position": "Delantero",
        "teamId": "19",
    }
    player = Player.from_api(data)
    assert player.id == "1001"
    assert player.name == "Vinicius Jr"
    assert player.position == "Delantero"
    assert player.team_id == "19"
    assert player.market_value is None
    assert player.points is None
    assert player.average_points is None


def test_league_standing_from_api():
    data = {
        "id": "team_77",
        "name": "Los Galacticos",
        "points": 450,
        "teamValue": 120000000,
        "manager": "Hugo",
    }
    standing = LeagueStanding.from_api("league_123", data, position=1)
    assert standing.league_team_id == "team_77"
    assert standing.league_id == "league_123"
    assert standing.team_name == "Los Galacticos"
    assert standing.manager_name == "Hugo"
    assert standing.points == 450
    assert standing.team_value == 120000000
    assert standing.position == 1


def test_league_movement_from_api():
    data = {
        "id": "mov_999",
        "playerId": "1001",
        "playerName": "Vinicius Jr",
        "fromTeamId": "team_1",
        "toTeamId": "team_2",
        "money": 75000000,
        "activityTypeId": 31,
        "created": "2026-09-01T10:00:00Z",
    }
    mov = LeagueMovement.from_api("league_123", data)
    assert mov.movement_id == "mov_999"
    assert mov.player_id == "1001"
    assert mov.player_name == "Vinicius Jr"
    assert mov.from_team_id == "team_1"
    assert mov.to_team_id == "team_2"
    assert mov.amount == 75000000
    assert mov.movement_type == 31


@responses.activate
def test_api_client_retry_and_throttle():
    client = FantasyApiClient(throttle_seconds=0.01, max_retries=2, timeout=5)
    test_url = "https://fantasy-api.llt-services.com/api/test-endpoint"

    # Primer intento falla con 500, segundo tiene éxito con 200
    responses.add(responses.GET, test_url, status=500)
    responses.add(responses.GET, test_url, json={"status": "ok"}, status=200)

    result = client.get(test_url)
    assert result == {"status": "ok"}
    assert len(responses.calls) == 2


def test_market_item_from_api():
    from fantasy.api.models import MarketItem

    data = {
        "id": "market_item_555",
        "player": {"id": "1001", "name": "Vinicius Jr"},
        "price": 85000000,
        "teamId": "19",
        "expirationDate": "2026-09-02T04:00:00Z",
    }
    item = MarketItem.from_api("league_123", data)
    assert item.market_id == "market_item_555"
    assert item.league_id == "league_123"
    assert item.player_id == "1001"
    assert item.price == 85000000
    assert item.owner_team_id == "19"
    assert item.expires_at == "2026-09-02T04:00:00Z"


def test_extract_gameweek_stats():
    from fantasy.collect.players import extract_gameweek_stats

    raw_payload = [
        {
            "id": "1001",
            "name": "Vinicius Jr",
            "playerStats": [
                {"weekNumber": 1, "points": 8, "minutes": 90, "goals": 1},
                {"weekNumber": 2, "points": 5, "minutes": 75, "goals": 0},
            ],
        },
        {
            "id": "1002",
            "name": "Courtois",
            "stats": [
                {"gameweek": 1, "points": 6, "minutes": 90},
            ],
        },
    ]
    stats = extract_gameweek_stats(raw_payload)
    assert len(stats) == 3
    assert stats[0].player_id == "1001"
    assert stats[0].gameweek == 1
    assert stats[0].points == 8
    assert stats[0].goals == 1
    assert stats[2].player_id == "1002"
    assert stats[2].gameweek == 1
    assert stats[2].points == 6



# ---------------------------------------------------------------------------
# Detalle de jugador: única fuente de minutos y estadísticas finas.
# Los payloads de abajo son la forma REAL verificada contra la API en vivo.
# ---------------------------------------------------------------------------

REAL_DETAIL_PAYLOAD = {
    "playerMaster": {
        "id": "68",
        "nickname": "Unai Simón",
        "playerStats": [
            {
                "weekNumber": 3,
                "totalPoints": 10,
                "stats": {
                    "mins_played": [90, 2],
                    "goals": [0, 0],
                    "goal_assist": [0, 0],
                    "saves": [2, 1],
                    "yellow_card": [0, 0],
                    "red_card": [0, 0],
                    "goals_conceded": [1, -1],
                },
            },
            {
                "weekNumber": 2,
                "totalPoints": 1,
                "stats": {"mins_played": [45, 1], "goals": [1, 5], "yellow_card": [1, -1]},
            },
        ],
    }
}


def test_gameweek_stat_from_detail_extrae_valor_no_puntos():
    """Cada métrica llega como par [valor, puntos]; se guarda el valor."""
    week = REAL_DETAIL_PAYLOAD["playerMaster"]["playerStats"][0]
    stat = PlayerGameweekStat.from_detail("68", week)

    assert stat is not None
    assert stat.gameweek == 3
    assert stat.points == 10
    # 90 es el valor; 2 son los puntos que otorga. No confundirlos.
    assert stat.minutes == 90
    assert stat.saves == 2
    assert stat.goals_conceded == 1
    # El diccionario completo se conserva para métricas futuras.
    assert stat.stats is not None and "mins_played" in stat.stats


def test_gameweek_stat_from_detail_sin_weeknumber_devuelve_none():
    assert PlayerGameweekStat.from_detail("68", {"totalPoints": 5, "stats": {}}) is None


def test_parse_player_detail_recorre_playermaster():
    stats = parse_player_detail(REAL_DETAIL_PAYLOAD, "68")
    assert len(stats) == 2
    assert {s.gameweek for s in stats} == {2, 3}
    assert sum(s.minutes for s in stats) == 135


def test_parse_player_detail_tolera_payload_inesperado():
    """Si el backend cambia de forma, se devuelve vacío en vez de reventar."""
    assert parse_player_detail(None, "68") == []
    assert parse_player_detail({}, "68") == []
    assert parse_player_detail({"playerMaster": {"playerStats": "roto"}}, "68") == []


def test_extract_gameweek_stats_lee_weekpoints_reales():
    """El listado global usa `weekPoints`, no `playerStats`. Formato verificado."""
    raw = [{"id": "68", "weekPoints": [{"weekNumber": 1, "points": 10}, {"weekNumber": 2, "points": 1}]}]
    stats = extract_gameweek_stats(raw)
    assert len(stats) == 2
    assert stats[0].points == 10
    # El listado no trae minutos: deben quedar a None, nunca a 0.
    assert stats[0].minutes is None

def test_league_from_api_tolerant():
    league = League.from_api({"id": 123, "name": "Liga Pascu", "team": {"id": "t9", "money": "4500000"}})
    assert league.id == "123"
    assert league.name == "Liga Pascu"
    assert league.team_id == "t9"
    assert league.team_money == 4500000

    # Sin equipo ni nombre: no inventa saldo, y el nombre cae a algo reconocible.
    bare = League.from_api({"id": "7"})
    assert bare.name == "Liga 7"
    assert bare.team_id is None
    assert bare.team_money is None


@responses.activate
def test_get_user_leagues_lista_plana_y_envuelta():
    from fantasy.api import endpoints

    client = FantasyApiClient(throttle_seconds=0)
    url = endpoints.user_leagues_url()

    responses.add(responses.GET, url, json=[{"id": "1", "name": "A"}, {"id": "2", "name": "B"}, {"name": "sin id"}])
    leagues, _ = client.get_user_leagues()
    assert [(lg.id, lg.name) for lg in leagues] == [("1", "A"), ("2", "B")]

    responses.replace(responses.GET, url, json={"elements": [{"id": "3", "name": "C"}]})
    leagues, _ = client.get_user_leagues()
    assert [lg.id for lg in leagues] == ["3"]


# Payload real de /v1/competition/1/leagues/{id}/teams/{id}, recortado.
SQUAD_PLAYER_REAL = {
    "buyoutClause": 2253350,
    "managerId": 6211313,
    "playerTeamId": "90389155",
    "buyoutClauseLockedEndTime": "2026-10-28T19:28:27+01:00",
    "isShielded": False,
    "manager": {"id": "6211313", "managerName": "Sakito_01"},
    "playerMaster": {
        "id": "2078",
        "name": "Diego Pablo Simeone",
        "nickname": "Simeone",
        "positionId": 5,
        "marketValue": 887335,
        "points": 12,
        "averagePoints": 1.5,
        "team": {"id": "7", "name": "Atlético de Madrid"},
        "images": {"transparent": {"256x256": "https://x/p2078.png"}},
    },
}


def test_squad_player_lee_clausula_y_bloqueo():
    sp = SquadPlayer.from_api("018021020", "38164437", SQUAD_PLAYER_REAL)
    assert sp.player_name == "Simeone"
    assert sp.position == "Entrenador"
    assert sp.buyout_clause == 2253350
    assert sp.market_value == 887335
    assert sp.club_name == "Atlético de Madrid"
    assert sp.player_team_id == "90389155"
    assert sp.manager_name == "Sakito_01"
    assert sp.image_url == "https://x/p2078.png"
    # El offset de la zona no se pierde: un clausulazo se juega al segundo.
    assert sp.clause_locked_until is not None
    assert sp.clause_locked_until.utcoffset() == timedelta(hours=1)


def test_squad_player_clause_open_respeta_fecha_y_escudo():
    sp = SquadPlayer.from_api("1", "2", SQUAD_PLAYER_REAL)
    antes = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
    despues = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
    assert sp.clause_open(antes) is False
    assert sp.clause_open(despues) is True

    # Un escudo activo bloquea aunque la fecha ya haya pasado.
    escudado = SquadPlayer.from_api("1", "2", {**SQUAD_PLAYER_REAL, "isShielded": True})
    assert escudado.clause_open(despues) is False

    # Sin fecha de bloqueo la API indica que nunca estuvo bloqueada.
    sin_fecha = SquadPlayer.from_api(
        "1", "2", {**SQUAD_PLAYER_REAL, "buyoutClauseLockedEndTime": None}
    )
    assert sin_fecha.clause_open(antes) is True


def test_squad_player_tolera_payload_incompleto():
    sp = SquadPlayer.from_api("1", "2", {})
    assert sp.player_name == "Desconocido"
    assert sp.buyout_clause is None
    assert sp.clause_locked_until is None
    assert sp.position is None
    # Sin fecha y sin escudo cuenta como abierta, igual que en la API.
    assert sp.clause_open() is True

    basura = SquadPlayer.from_api(
        "1", "2", {"buyoutClause": "no-un-numero", "buyoutClauseLockedEndTime": "ayer"}
    )
    assert basura.buyout_clause is None
    assert basura.clause_locked_until is None


@responses.activate
def test_get_league_team_incluye_cedidos():
    from fantasy.api import endpoints

    client = FantasyApiClient(throttle_seconds=0)
    url = endpoints.league_team_url("018021020", "38164437")

    cedido = {**SQUAD_PLAYER_REAL, "playerTeamId": "999"}
    responses.add(
        responses.GET,
        url,
        json={"players": [SQUAD_PLAYER_REAL], "loanedPlayers": [cedido], "teamValue": 1},
    )
    jugadores, raw = client.get_league_team("018021020", "38164437")
    # Los cedidos siguen siendo clausulables, así que cuentan.
    assert [j.player_team_id for j in jugadores] == ["90389155", "999"]
    assert raw["teamValue"] == 1


@responses.activate
def test_get_league_team_tolera_respuesta_rara():
    from fantasy.api import endpoints

    client = FantasyApiClient(throttle_seconds=0)
    url = endpoints.league_team_url("1", "2")
    responses.add(responses.GET, url, json=[])
    jugadores, _ = client.get_league_team("1", "2")
    assert jugadores == []
