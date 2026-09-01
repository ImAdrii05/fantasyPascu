"""Tests unitarios para los modelos y cliente de la API de LaLiga Fantasy."""

import responses
import pytest

from fantasy.api import FantasyApiClient, FantasyApiError
from fantasy.api.models import Team, Player, LeagueStanding, LeagueMovement
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

