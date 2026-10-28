"""Modelos de datos tolerantes para deserializar las respuestas de la API de LaLiga Fantasy."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

# Mapeo de positionId -> nombre de posición, verificado contra la respuesta real
# del listado global de jugadores (el único campo que llega es `positionId`).
POSITION_BY_ID: dict[int, str] = {
    1: "Portero",
    2: "Defensa",
    3: "Centrocampista",
    4: "Delantero",
    5: "Entrenador",
}


# La API manda números como cadena, como null y a veces ausentes. El resto del
# fichero resuelve eso con un try/except por campo; en la plantilla hay cinco
# seguidos, así que aquí se hace una vez.
def _as_int(valor: Any) -> int | None:
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(valor: Any) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _as_datetime(valor: Any) -> datetime | None:
    """Convierte un ISO-8601 con zona en datetime consciente de zona."""
    if not valor:
        return None
    try:
        # Python acepta "+01:00" pero no la "Z" hasta 3.11.
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


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

        # Posición. VERIFICADO contra la API real: el listado global NO devuelve
        # un campo `position` de texto, solo `positionId` como cadena ("1".."5").
        position_id = data.get("positionId")
        if position_id is not None:
            try:
                position_id = int(position_id)
            except (ValueError, TypeError):
                position_id = None
        pos = data.get("position") or POSITION_BY_ID.get(position_id)

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
    second_yellow_cards: int | None = None
    own_goals: int | None = None
    saves: int | None = None
    goals_conceded: int | None = None
    stats: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, player_id: str | int, gameweek: int, data: dict[str, Any]) -> "PlayerGameweekStat":
        """Construye desde el listado global, donde cada jornada solo trae puntos.

        Formato real verificado: `weekPoints` = [{"weekNumber": N, "points": P}, ...].
        """
        return cls(
            player_id=str(player_id),
            gameweek=int(gameweek),
            points=data.get("points") if data.get("points") is not None else data.get("totalPoints"),
            minutes=data.get("minutes"),
            goals=data.get("goals"),
            assists=data.get("assists"),
            yellow_cards=data.get("yellowCards") or data.get("yellow_cards"),
            red_cards=data.get("redCards") or data.get("red_cards"),
        )

    @classmethod
    def from_detail(cls, player_id: str | int, data: dict[str, Any]) -> "PlayerGameweekStat | None":
        """Construye desde el detalle del jugador, que sí trae minutos y estadísticas finas.

        Formato real verificado (`playerMaster.playerStats[]`):
            {"weekNumber": 3, "totalPoints": 10, "stats": {"mins_played": [90, 2], ...}}
        Cada métrica es un par [valor, puntos]; aquí se guarda el VALOR, y el
        diccionario íntegro se conserva en `stats` para no perder nada.
        """
        gw = data.get("weekNumber")
        if gw is None:
            return None
        try:
            gw = int(gw)
        except (ValueError, TypeError):
            return None

        raw_stats = data.get("stats") or {}

        def value_of(key: str) -> int | None:
            """Extrae el valor (primer elemento) del par [valor, puntos]."""
            pair = raw_stats.get(key)
            if isinstance(pair, (list, tuple)) and pair:
                try:
                    return int(pair[0])
                except (ValueError, TypeError):
                    return None
            if isinstance(pair, (int, float)):
                return int(pair)
            return None

        return cls(
            player_id=str(player_id),
            gameweek=gw,
            points=data.get("totalPoints"),
            minutes=value_of("mins_played"),
            goals=value_of("goals"),
            assists=value_of("goal_assist"),
            yellow_cards=value_of("yellow_card"),
            red_cards=value_of("red_card"),
            second_yellow_cards=value_of("second_yellow_card"),
            own_goals=value_of("own_goals"),
            saves=value_of("saves"),
            goals_conceded=value_of("goals_conceded"),
            stats=raw_stats or None,
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
    # managerId: la clave que permite cruzar esta tabla con la actividad de la liga,
    # que identifica a las personas por manager y no por equipo.
    manager_id: str | None = None

    @classmethod
    def from_api(cls, league_id: str, data: dict[str, Any], position: int | None = None) -> "LeagueStanding":
        team = data.get("team") or {}
        manager = team.get("manager") or {} if isinstance(team, dict) else {}

        team_id = str(data.get("id") or (team.get("id") if isinstance(team, dict) else "") or "")

        manager_name = (
            data.get("manager")
            or (manager.get("managerName") if isinstance(manager, dict) else None)
            or (manager.get("name") if isinstance(manager, dict) else None)
        )

        # VERIFICADO: la actividad de la liga referencia a las personas por managerId,
        # así que sin este campo no hay forma de saber de quién es cada movimiento.
        manager_id = None
        if isinstance(team, dict):
            manager_id = team.get("managerId") or (manager.get("id") if isinstance(manager, dict) else None)
        manager_id = str(manager_id) if manager_id else None

        # VERIFICADO: la clasificación real NO trae nombre de equipo, solo el del mánager.
        # `team_name` es NOT NULL en la tabla, así que se recurre al mánager antes que
        # dejarlo a None (que reventaría el insert) o inventar un nombre genérico.
        team_name = (
            data.get("name")
            or (team.get("name") if isinstance(team, dict) else None)
            or manager_name
            or f"Equipo {team_id}"
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
            manager_id=manager_id,
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
    # Identificadores de MANAGER (no de equipo). La actividad de la liga usa
    # managerId, que es la clave para reconstruir el dinero de cada persona.
    # En un traspaso entre mánagers aparecen los dos; contra el mercado, solo user1.
    user1_id: str | None = None
    user2_id: str | None = None
    # Solo en los ingresos por jornada (activityTypeId 6).
    week_number: int | None = None
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

        # VERIFICADO: la actividad real referencia al jugador como `playerMasterId`,
        # un entero suelto, no un objeto anidado.
        if not player_id and (data.get("playerMasterId") or data.get("playerId")):
            player_id = str(data.get("playerMasterId") or data.get("playerId"))
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
        # VERIFICADO: el campo real es `createdAt` (ISO con zona horaria). Antes se
        # buscaba `created`/`date`/`timestamp` y los 108 movimientos quedaban sin fecha,
        # lo que hace imposible ordenar el libro mayor.
        m_date = data.get("createdAt") or data.get("created") or data.get("date") or data.get("timestamp")

        user1_id = str(data["user1Id"]) if data.get("user1Id") else None
        user2_id = str(data["user2Id"]) if data.get("user2Id") else None

        week_number = data.get("weekNumber")
        if week_number is not None:
            try:
                week_number = int(week_number)
            except (ValueError, TypeError):
                week_number = None

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
            user1_id=user1_id,
            user2_id=user2_id,
            week_number=week_number,
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

        # `salePrice` es el precio de la puja; va primero porque es la clave que usa
        # de verdad el mercado. Sin ella el precio quedaba a NULL en todas las filas.
        price = (
            data.get("salePrice")
            or data.get("price")
            or data.get("marketValue")
            or data.get("buyoutClause")
        )
        if price is not None:
            try:
                price = int(price)
            except (ValueError, TypeError):
                price = None

        # VERIFICADO contra el payload real: cuando un mánager pone a un jugador en
        # venta, el vendedor llega en `sellerTeam.id`, no en `teamId` ni en `team.id`.
        # Buscar solo esas dos claves dejaba `owner_team_id` siempre a None, y con él
        # se pierde lo único que separa a los agentes libres que saca la liga
        # (`marketPlayerLeague`, sin vendedor) de los que vende otro (`marketPlayerTeam`).
        seller_obj = data.get("sellerTeam") or {}
        team_obj = data.get("team") or {}
        owner_team_id = (
            str(
                (seller_obj.get("id") if isinstance(seller_obj, dict) else "")
                or data.get("teamId")
                or (team_obj.get("id") if isinstance(team_obj, dict) else "")
                or ""
            )
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



@dataclass
class League:
    """Liga privada en la que participa el usuario autenticado.

    Sale del endpoint de ligas del usuario. `id` y `name` son los que lee también
    LaLigaApp; `team.money` es el saldo propio (el único saldo que da la API, ver
    collect/league.py). El resto se lee de forma tolerante por si cambia el formato.
    """
    id: str
    name: str
    team_id: str | None = None
    team_money: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "League":
        league_id = str(data.get("id") or data.get("leagueId") or "")
        name = data.get("name") or f"Liga {league_id}"

        team = data.get("team") if isinstance(data.get("team"), dict) else {}
        team_id = team.get("id") or data.get("teamId")

        money = team.get("money") if team.get("money") is not None else team.get("teamMoney")
        if money is not None:
            try:
                money = int(money)
            except (ValueError, TypeError):
                money = None

        return cls(
            id=league_id,
            name=str(name),
            team_id=str(team_id) if team_id else None,
            team_money=money,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SquadPlayer:
    """Un jugador dentro de la plantilla de un mánager, con su cláusula.

    La cláusula es dato vivo, no histórico: lo que importa es cuánto cuesta
    AHORA y a qué hora exacta se abre. Por eso este modelo no se guarda en la
    base como snapshot diario, se pide a la API en el momento.
    """
    league_id: str
    league_team_id: str
    manager_id: str | None
    manager_name: str | None
    player_id: str
    player_name: str
    position: str | None = None
    position_id: int | None = None
    club_name: str | None = None
    image_url: str | None = None
    market_value: int | None = None
    points: int | None = None
    average_points: float | None = None
    buyout_clause: int | None = None
    # Hora exacta a la que la cláusula queda pagable. Llega en ISO con zona
    # (`2026-10-28T19:28:27+01:00`), así que se conserva con su offset: un
    # clausulazo se juega al segundo y convertir a naive perdería la hora real.
    clause_locked_until: datetime | None = None
    is_shielded: bool = False
    player_team_id: str | None = None

    @classmethod
    def from_api(cls, league_id: str, league_team_id: str, data: dict[str, Any]) -> "SquadPlayer":
        master = data.get("playerMaster") or {}
        manager = data.get("manager") or {}
        club = master.get("team") or {}

        position_id = master.get("positionId")
        try:
            position_id = int(position_id) if position_id is not None else None
        except (TypeError, ValueError):
            position_id = None

        imagenes = (master.get("images") or {}).get("transparent") or {}
        image_url = imagenes.get("256x256") or imagenes.get("128x128")

        return cls(
            league_id=str(league_id),
            league_team_id=str(league_team_id),
            manager_id=str(data.get("managerId")) if data.get("managerId") else None,
            manager_name=manager.get("managerName") if isinstance(manager, dict) else None,
            player_id=str(master.get("id") or ""),
            player_name=master.get("nickname") or master.get("name") or "Desconocido",
            position=POSITION_BY_ID.get(position_id) if position_id else None,
            position_id=position_id,
            club_name=club.get("name") if isinstance(club, dict) else None,
            image_url=image_url,
            market_value=_as_int(master.get("marketValue")),
            points=_as_int(master.get("points")),
            average_points=_as_float(master.get("averagePoints")),
            buyout_clause=_as_int(data.get("buyoutClause")),
            clause_locked_until=_as_datetime(data.get("buyoutClauseLockedEndTime")),
            is_shielded=bool(data.get("isShielded")),
            player_team_id=str(data.get("playerTeamId")) if data.get("playerTeamId") else None,
        )

    def clause_open(self, ahora: datetime | None = None) -> bool:
        """True si la cláusula se puede pagar ya.

        Un escudo activo la bloquea aunque la fecha haya pasado, y una fecha
        ausente se trata como abierta: es lo que devuelve la API cuando nunca
        hubo bloqueo.
        """
        if self.is_shielded:
            return False
        if self.clause_locked_until is None:
            return True
        ahora = ahora or datetime.now(timezone.utc)
        return self.clause_locked_until <= ahora

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
