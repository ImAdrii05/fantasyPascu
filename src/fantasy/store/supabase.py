"""Operaciones idempotentes de persistencia y upsert en Supabase."""

from datetime import date, datetime, timezone
import logging
from typing import Any
from supabase import create_client, Client

from fantasy.api.models import Team, Player, PlayerGameweekStat, LeagueStanding, LeagueMovement, MarketItem
from fantasy import config

logger = logging.getLogger(__name__)


def chunk_list(items: list[Any], chunk_size: int = 400):
    """Generador que divide una lista en bloques para evitar exceder límites de payload."""
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


# PostgREST limita las respuestas a 1000 filas por defecto y NO avisa: devuelve
# menos datos sin error. Con 813 jugadores diarios, cualquier lectura de histórico
# supera ese techo al segundo día, así que toda lectura masiva debe paginar.
PAGE_SIZE = 1000


def fetch_all(query_builder, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Ejecuta una consulta paginando hasta agotar los resultados.

    Args:
        query_builder: Función sin argumentos que devuelve un query de PostgREST
            ya filtrado y ordenado, listo para aplicarle `.range()`.

    Returns:
        Todas las filas, no solo las primeras 1000.
    """
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = query_builder().range(start, start + page_size - 1).execute()
        batch = page.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


class SupabaseStore:
    """Capa de acceso a datos para Supabase/Postgres."""

    def __init__(self, client: Client | None = None):
        if client is not None:
            self.client = client
        else:
            config.validate_supabase_config()
            self.client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

    def save_raw_snapshot(self, endpoint: str, payload: Any, snapshot_date: str | date | None = None) -> None:
        """Guarda el JSON crudo de la respuesta en la tabla raw_snapshots."""
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()
        elif isinstance(snapshot_date, date):
            snapshot_date = snapshot_date.isoformat()

        row = {
            "snapshot_date": snapshot_date,
            "endpoint": endpoint,
            "payload": payload,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.client.table("raw_snapshots").insert(row).execute()
            logger.debug(f"Raw snapshot guardado para endpoint '{endpoint}' en fecha {snapshot_date}")
        except Exception as e:
            logger.error(f"Error al guardar raw snapshot para '{endpoint}': {e}")
            raise

    def upsert_teams(self, teams: list[Team]) -> int:
        """Realiza un upsert de los equipos maestros."""
        if not teams:
            return 0
        rows = [
            {
                "id": t.id,
                "name": t.name,
                "short_name": t.short_name,
                "slug": t.slug,
                "badge_url": t.badge_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            for t in teams
            if t.id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("teams").upsert(chunk, on_conflict="id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} equipos en Supabase.")
        return count

    def upsert_players(self, players: list[Player]) -> int:
        """Realiza un upsert de la información dimensional de los jugadores."""
        if not players:
            return 0
        rows = [
            {
                "id": p.id,
                "name": p.name,
                "nickname": p.nickname,
                "slug": p.slug,
                "position": p.position,
                "position_id": p.position_id,
                "team_id": p.team_id,
                "status": p.status,
                "image_url": p.image_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            for p in players
            if p.id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("players").upsert(chunk, on_conflict="id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} registros en tabla players.")
        return count

    def upsert_player_daily(
        self,
        players: list[Player],
        snapshot_date: str | date | None = None,
        minutes_by_player: dict[str, int] | None = None,
    ) -> int:
        """Guarda la foto diaria de valor de mercado y puntos de cada jugador (Idempotente).

        Args:
            minutes_by_player: Minutos totales por jugador agregados desde el detalle.
                El listado global no trae minutos, así que sin este mapa la columna
                `minutes_played` queda a NULL (nunca a 0, que falsearía las medias).
        """
        if not players:
            return 0
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()
        elif isinstance(snapshot_date, date):
            snapshot_date = snapshot_date.isoformat()

        rows = [
            {
                "snapshot_date": snapshot_date,
                "player_id": p.id,
                "market_value": p.market_value,
                "points": p.points,
                "average_points": p.average_points,
                "played_matches": p.played_matches,
                "minutes_played": (minutes_by_player or {}).get(p.id, p.minutes_played),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for p in players
            if p.id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("player_daily").upsert(chunk, on_conflict="snapshot_date,player_id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} registros diarios en player_daily para fecha {snapshot_date}.")
        return count

    def upsert_player_gameweek_stats(self, stats: list[PlayerGameweekStat]) -> int:
        """Guarda las estadísticas por jornada de cada jugador."""
        if not stats:
            return 0
        rows = [
            {
                "player_id": s.player_id,
                "gameweek": s.gameweek,
                "points": s.points,
                "minutes": s.minutes,
                "goals": s.goals,
                "assists": s.assists,
                "yellow_cards": s.yellow_cards,
                "red_cards": s.red_cards,
                "second_yellow_cards": s.second_yellow_cards,
                "own_goals": s.own_goals,
                "saves": s.saves,
                "goals_conceded": s.goals_conceded,
                "stats": s.stats,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for s in stats
            if s.player_id and s.gameweek
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("player_gameweek_stats").upsert(chunk, on_conflict="player_id,gameweek").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} registros en player_gameweek_stats.")
        return count

    def upsert_league_standings(self, standings: list[LeagueStanding], snapshot_date: str | date | None = None) -> int:
        """Guarda la clasificación de la liga privada en la fecha actual (Idempotente)."""
        if not standings:
            return 0
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()
        elif isinstance(snapshot_date, date):
            snapshot_date = snapshot_date.isoformat()

        rows = [
            {
                "snapshot_date": snapshot_date,
                "league_team_id": s.league_team_id,
                "league_id": s.league_id,
                "team_name": s.team_name,
                "manager_name": s.manager_name,
                "team_value": s.team_value,
                "points": s.points,
                "position": s.position,
                "manager_id": s.manager_id,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for s in standings
            if s.league_team_id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("league_standings").upsert(chunk, on_conflict="snapshot_date,league_team_id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} registros en league_standings para fecha {snapshot_date}.")
        return count

    def upsert_league_market(self, market_items: list[MarketItem], snapshot_date: str | date | None = None) -> int:
        """Guarda el snapshot diario del mercado de la liga privada (Idempotente)."""
        if not market_items:
            return 0
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()
        elif isinstance(snapshot_date, date):
            snapshot_date = snapshot_date.isoformat()

        rows = [
            {
                "snapshot_date": snapshot_date,
                "league_id": m.league_id,
                "market_id": m.market_id,
                "player_id": m.player_id,
                "price": m.price,
                "owner_team_id": m.owner_team_id,
                "expires_at": m.expires_at,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for m in market_items
            if m.market_id and m.league_id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("league_market").upsert(chunk, on_conflict="snapshot_date,league_id,market_id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} items en league_market para fecha {snapshot_date}.")
        return count

    def upsert_league_movements(self, movements: list[LeagueMovement]) -> int:
        """Guarda los movimientos de mercado y actividad de la liga."""
        if not movements:
            return 0
        rows = [
            {
                "movement_id": m.movement_id,
                "league_id": m.league_id,
                "player_id": m.player_id,
                "player_name": m.player_name,
                "from_team_id": m.from_team_id,
                "to_team_id": m.to_team_id,
                "amount": m.amount,
                "movement_type": str(m.movement_type) if m.movement_type is not None else None,
                "movement_date": m.movement_date,
                "user1_id": m.user1_id,
                "user2_id": m.user2_id,
                "week_number": m.week_number,
                "raw_payload": m.raw_payload,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            for m in movements
            if m.movement_id
        ]
        count = 0
        for chunk in chunk_list(rows):
            self.client.table("league_movements").upsert(chunk, on_conflict="movement_id").execute()
            count += len(chunk)
        logger.info(f"Upsert de {count} movimientos en league_movements.")
        return count


_default_supabase_store: SupabaseStore | None = None


def get_supabase_store() -> SupabaseStore:
    """Devuelve la instancia singleton de la capa de persistencia Supabase."""
    global _default_supabase_store
    if _default_supabase_store is None:
        _default_supabase_store = SupabaseStore()
    return _default_supabase_store
