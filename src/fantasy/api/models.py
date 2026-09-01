"""Modelos de datos tolerantes para deserializar las respuestas de la API de LaLiga Fantasy."""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Team:
    """Equipo de LaLiga (maestro de equipos)."""
    id: str
    name: str
    short_name: str | None = None
    slug: str | None = None
    badge_url: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Team":
        team_id = str(data.get("id") or "")
        name = data.get("name") or data.get("shortName") or "Desconocido"
        short_name = data.get("shortName") or data.get("short_name")
        slug = data.get("slug")
        badge_url = (
            data.get("badgeColor")
            or data.get("badgeWhite")
            or data.get("badge_url")
            or (data.get("images") or {}).get("badge")
        )
        return cls(
            id=team_id,
            name=name,
            short_name=short_name,
            slug=slug,
            badge_url=badge_url,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Player:
    """Datos generales y de snapshot de un jugador."""
    id: str
    name: str
    nickname: str | None = None
    slug: str | None = None
    position: str | None = None
    position_id: int | None = None
    team_id: str | None = None
    status: str | None = None
    market_value: int | None = None
    points: int | None = None
    average_points: float | None = None
    played_matches: int | None = None
    minutes_played: int | None = None
    image_url: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Player":
        player_id = str(data.get("id") or data.get("playerId") or "")
        name = data.get("name") or data.get("nickname") or "Desconocido"
        nickname = data.get("nickname")
        slug = data.get("slug")

        # Posición
        pos = data.get("position")
        position_id = data.get("positionId")
        if position_id is not None:
            try:
                position_id = int(position_id)
            except (ValueError, TypeError):
                position_id = None

        # Equipo
        team_id = None
        if data.get("teamId") is not None:
            team_id = str(data["teamId"])
        elif isinstance(data.get("team"), dict) and data["team"].get("id") is not None:
            team_id = str(data["team"]["id"])

        # Estado (ok, lesionado, sancionado, duda...)
        status = data.get("playerStatus") or data.get("status")

        # Métricas de mercado y puntos (None si no están presentes, NUNCA forzar 0)
        market_value = data.get("marketValue") or data.get("price")
        if market_value is not None:
            try:
                market_value = int(market_value)
            except (ValueError, TypeError):
                market_value = None

        points = data.get("points")
        if points is not None:
            try:
                points = int(points)
            except (ValueError, TypeError):
                points = None

        average_points = data.get("averagePoints") or data.get("avgPoints")
        if average_points is not None:
            try:
                average_points = float(average_points)
            except (ValueError, TypeError):
                average_points = None

        played_matches = data.get("playedMatches") or data.get("matches")
        if played_matches is not None:
            try:
                played_matches = int(played_matches)
            except (ValueError, TypeError):
                played_matches = None

        minutes_played = data.get("minutesPlayed") or data.get("minutes")
        if minutes_played is not None:
            try:
                minutes_played = int(minutes_played)
            except (ValueError, TypeError):
                minutes_played = None

        # Imagen
        images = data.get("images") or {}
        image_url = (
            data.get("image")
            or (images.get("transparent") or {}).get("256x256")
            or images.get("player")
        )

        return cls(
            id=player_id,
            name=name,
            nickname=nickname,
            slug=slug,
            position=pos,
            position_id=position_id,
            team_id=team_id,
            status=status,
            market_value=market_value,
            points=points,
            average_points=average_points,
            played_matches=played_matches,
            minutes_played=minutes_played,
            image_url=image_url,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlayerGameweekStat:
    """Estadísticas de un jugador para una jornada específica."""
    player_id: str
    gameweek: int
    points: int | None = None
    minutes: int | None = None
    goals: int | None = None
    assists: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None

    @classmethod
    def from_api(cls, player_id: str | int, gameweek: int, data: dict[str, Any]) -> "PlayerGameweekStat":
        return cls(
            player_id=str(player_id),
            gameweek=int(gameweek),
            points=data.get("points"),
            minutes=data.get("minutes"),
            goals=data.get("goals"),
            assists=data.get("assists"),
            yellow_cards=data.get("yellowCards") or data.get("yellow_cards"),
            red_cards=data.get("redCards") or data.get("red_cards"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeagueStanding:
    """Fila de la clasificación de una liga privada."""
    league_team_id: str
    league_id: str
    team_name: str
    manager_name: str | None = None
    team_value: int | None = None
    points: int | None = None
    position: int | None = None

    @classmethod
    def from_api(cls, league_id: str, data: dict[str, Any], position: int | None = None) -> "LeagueStanding":
        team = data.get("team") or {}
        manager = team.get("manager") or {} if isinstance(team, dict) else {}

        team_id = str(data.get("id") or (team.get("id") if isinstance(team, dict) else "") or "")
        team_name = data.get("name") or (team.get("name") if isinstance(team, dict) else "Equipo")

        manager_name = (
            data.get("manager")
            or (manager.get("managerName") if isinstance(manager, dict) else None)
            or (manager.get("name") if isinstance(manager, dict) else None)
        )

        team_val = data.get("teamValue") or (team.get("teamValue") if isinstance(team, dict) else None)
        if team_val is not None:
            try:
                team_val = int(team_val)
            except (ValueError, TypeError):
                team_val = None

        pts = data.get("points") or (team.get("teamPoints") or team.get("points") if isinstance(team, dict) else None)
        if pts is not None:
            try:
                pts = int(pts)
            except (ValueError, TypeError):
                pts = None

        pos = data.get("position") or position
        if pos is not None:
            try:
                pos = int(pos)
            except (ValueError, TypeError):
                pos = None

        return cls(
            league_team_id=team_id,
            league_id=str(league_id),
            team_name=team_name,
            manager_name=manager_name,
            team_value=team_val,
            points=pts,
            position=pos,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeagueMovement:
    """Movimiento de mercado o actividad en una liga privada."""
    movement_id: str
    league_id: str
    player_id: str | None = None
    player_name: str | None = None
    from_team_id: str | None = None
    to_team_id: str | None = None
    amount: int | None = None
    movement_type: int | str | None = None
    movement_date: str | None = None
    raw_payload: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, league_id: str, data: dict[str, Any]) -> "LeagueMovement":
        mov_id = str(data.get("id") or data.get("activityId") or "")
        player_data = data.get("playerMaster") or data.get("player") or {}
        player_id = None
        player_name = None

        if isinstance(player_data, dict):
            if player_data.get("id"):
                player_id = str(player_data["id"])
            player_name = player_data.get("nickname") or player_data.get("name")

        if not player_id and data.get("playerId"):
            player_id = str(data["playerId"])
        if not player_name and data.get("playerName"):
            player_name = str(data["playerName"])

        from_team_id = str(data.get("fromTeamId") or data.get("from_team_id") or "") or None
        to_team_id = str(data.get("toTeamId") or data.get("to_team_id") or data.get("teamId") or "") or None

        amount = data.get("money") or data.get("amount") or data.get("price")
        if amount is not None:
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = None

        m_type = data.get("activityTypeId") or data.get("type") or data.get("action")
        m_date = data.get("created") or data.get("date") or data.get("timestamp")

        return cls(
            movement_id=mov_id,
            league_id=str(league_id),
            player_id=player_id,
            player_name=player_name,
            from_team_id=from_team_id,
            to_team_id=to_team_id,
            amount=amount,
            movement_type=m_type,
            movement_date=str(m_date) if m_date else None,
            raw_payload=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketItem:
    """Jugador o ítem en el mercado de una liga privada."""
    market_id: str
    league_id: str
    player_id: str | None = None
    price: int | None = None
    owner_team_id: str | None = None
    expires_at: str | None = None
    raw_payload: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, league_id: str, data: dict[str, Any]) -> "MarketItem":
        market_id = str(data.get("id") or data.get("marketId") or "")
        player_obj = data.get("player") or data.get("playerMaster") or {}
        player_id = None
        if isinstance(player_obj, dict) and player_obj.get("id"):
            player_id = str(player_obj["id"])
        elif data.get("playerId"):
            player_id = str(data["playerId"])

        price = data.get("price") or data.get("marketValue") or data.get("buyoutClause")
        if price is not None:
            try:
                price = int(price)
            except (ValueError, TypeError):
                price = None

        team_obj = data.get("team") or {}
        owner_team_id = (
            str(data.get("teamId") or (team_obj.get("id") if isinstance(team_obj, dict) else "") or "")
            or None
        )

        expires_at = data.get("expirationDate") or data.get("expiresAt") or data.get("expiration")

        return cls(
            market_id=market_id,
            league_id=str(league_id),
            player_id=player_id,
            price=price,
            owner_team_id=owner_team_id,
            expires_at=str(expires_at) if expires_at else None,
            raw_payload=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

