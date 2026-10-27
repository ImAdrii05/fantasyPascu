"""Cliente HTTP para la API de LaLiga Fantasy con autenticación, throttle y reintentos."""

import logging
import time
from typing import Any
import requests

from fantasy.auth import get_access_token, AuthExpired
from fantasy.api import endpoints
from fantasy.api.models import Team, Player, League, LeagueStanding, LeagueMovement

logger = logging.getLogger(__name__)


class FantasyApiError(Exception):
    """Excepción base para errores de la API de Fantasy."""

    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class FantasyApiClient:
    """Cliente HTTP con gestión de sesión, reintentos con backoff y throttle de cortesía."""

    def __init__(
        self,
        throttle_seconds: float = 0.5,
        max_retries: int = 3,
        timeout: int = 20,
    ):
        self.throttle_seconds = throttle_seconds
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self._last_request_time: float = 0.0

    def _throttle(self) -> None:
        """Aplica una breve pausa entre peticiones sucesivas."""
        if self.throttle_seconds > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.throttle_seconds:
                time.sleep(self.throttle_seconds - elapsed)
        self._last_request_time = time.time()

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        """Ejecuta una petición HTTP con autorización Bearer, throttle y backoff exponencial."""
        token = get_access_token(force_refresh=False)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/json",
            "x-lang": "es",
        }

        retries = 0
        backoff_delay = 1.0

        while True:
            self._throttle()
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_data,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                retries += 1
                if retries > self.max_retries:
                    raise FantasyApiError(f"Fallo de conexión tras {self.max_retries} reintentos: {e}") from e
                logger.warning(f"Error de red ({e}). Reintentando en {backoff_delay:.1f}s (intento {retries}/{self.max_retries})...")
                time.sleep(backoff_delay)
                backoff_delay *= 2
                continue

            # Manejo de 401 (token expirado) con un único reintento forzando refresco
            if response.status_code == 401 and retry_on_401:
                logger.info("Recibido HTTP 401. Forzando refresco de token y reintentando...")
                try:
                    new_token = get_access_token(force_refresh=True)
                    headers["Authorization"] = f"Bearer {new_token}"
                    return self.request(
                        method=method,
                        url=url,
                        params=params,
                        json_data=json_data,
                        retry_on_401=False,  # Un único reintento
                    )
                except Exception as e:
                    raise AuthExpired(f"Error al renovar token tras HTTP 401: {e}") from e

            # Reintento con backoff para 429 (Too Many Requests) o errores de servidor (5xx)
            if response.status_code in (429, 500, 502, 503, 504):
                retries += 1
                if retries > self.max_retries:
                    raise FantasyApiError(
                        f"Error HTTP {response.status_code} tras {self.max_retries} reintentos: {response.text[:300]}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )
                wait_time = backoff_delay
                # Si el servidor envía Retry-After en 429, respetarlo
                if response.status_code == 429 and "Retry-After" in response.headers:
                    try:
                        wait_time = float(response.headers["Retry-After"])
                    except ValueError:
                        pass
                logger.warning(f"HTTP {response.status_code}. Pausando {wait_time:.1f}s antes de reintentar...")
                time.sleep(wait_time)
                backoff_delay *= 2
                continue

            if not response.ok:
                raise FantasyApiError(
                    f"Error HTTP {response.status_code} en {url}: {response.text[:300]}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            # Si es 204 No Content
            if response.status_code == 204:
                return None

            try:
                return response.json()
            except Exception as e:
                raise FantasyApiError(
                    f"La respuesta de {url} no es JSON válido: {response.text[:300]}",
                    status_code=response.status_code,
                    response_body=response.text,
                ) from e

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", url, params=params)

    def get_teams_master(self) -> tuple[list[Team], Any]:
        """Obtiene la lista de equipos maestros. Devuelve (lista_equipos, raw_json)."""
        url = endpoints.teams_master_url()
        raw = self.get(url)
        # Soportar array plano o {data: {teams: [...]}}
        items = raw if isinstance(raw, list) else (raw.get("teams") or (raw.get("data") or {}).get("teams") or [])
        teams = [Team.from_api(t) for t in items if isinstance(t, dict)]
        return teams, raw

    def get_all_players(self) -> tuple[list[Player], Any]:
        """Obtiene la lista global de jugadores de la competición. Devuelve (lista_jugadores, raw_json)."""
        url = endpoints.all_players_url()
        raw = self.get(url)
        items = raw if isinstance(raw, list) else (raw.get("elements") or (raw.get("data") or {}).get("elements") or (raw.get("data") if isinstance(raw.get("data"), list) else []))
        players = [Player.from_api(p) for p in items if isinstance(p, dict)]
        return players, raw

    def get_user_leagues(self) -> tuple[list[League], Any]:
        """Obtiene las ligas del usuario autenticado. Devuelve (lista_ligas, raw_json)."""
        url = endpoints.user_leagues_url()
        raw = self.get(url)
        items = raw if isinstance(raw, list) else (raw.get("elements") or raw.get("leagues") or (raw.get("data") if isinstance(raw.get("data"), list) else []))
        leagues = [League.from_api(item) for item in items if isinstance(item, dict)]
        return [league for league in leagues if league.id], raw

    def get_league_market(self, league_id: str | int) -> tuple[list[dict[str, Any]], Any]:
        """Obtiene los jugadores en el mercado de una liga. Devuelve (items_mercado, raw_json)."""
        url = endpoints.league_market_url(league_id)
        raw = self.get(url)
        items = raw if isinstance(raw, list) else (raw.get("elements") or (raw.get("data") or {}).get("elements") or [])
        return items, raw

    def get_league_standing(self, league_id: str | int) -> tuple[list[LeagueStanding], Any]:
        """Obtiene la clasificación de la liga privada. Devuelve (lista_standing, raw_json)."""
        url = endpoints.league_standing_url(league_id)
        raw = self.get(url)
        items = raw if isinstance(raw, list) else (raw.get("elements") or (raw.get("data") or {}).get("elements") or (raw.get("data") if isinstance(raw.get("data"), list) else []))
        standings = [LeagueStanding.from_api(str(league_id), item, position=i+1) for i, item in enumerate(items) if isinstance(item, dict)]
        return standings, raw

    def get_league_activity(self, league_id: str | int, index: int = 0) -> tuple[list[LeagueMovement], Any]:
        """Obtiene UNA página del historial de actividad. Devuelve (movimientos, raw_json)."""
        url = endpoints.league_activity_url(league_id, index=index)
        raw = self.get(url)
        items = raw if isinstance(raw, list) else (raw.get("elements") or (raw.get("data") or {}).get("elements") or (raw.get("data") if isinstance(raw.get("data"), list) else []))
        movements = [LeagueMovement.from_api(str(league_id), item) for item in items if isinstance(item, dict)]
        return movements, raw

    def get_league_activity_all(
        self, league_id: str | int, max_pages: int = 50
    ) -> tuple[list[LeagueMovement], list[Any]]:
        """Recorre TODAS las páginas de actividad hasta agotar el histórico.

        El endpoint pagina por `index` y devuelve una lista vacía cuando ya no queda
        nada. Pedir solo `index=0` deja fuera el histórico antiguo, y sin el histórico
        completo es imposible reconstruir el dinero de cada mánager: falta justo el
        principio, que es donde arranca el saldo.

        `max_pages` es un tope de seguridad para no entrar en bucle infinito si el
        backend dejara de devolver páginas vacías al terminar.

        Returns:
            (movimientos de todas las páginas, lista de payloads crudos por página).
        """
        todos: list[LeagueMovement] = []
        crudos: list[Any] = []

        for index in range(max_pages):
            movimientos, raw = self.get_league_activity(league_id, index=index)
            if not movimientos:
                break
            todos.extend(movimientos)
            crudos.append(raw)
        else:
            logger.warning(
                f"Se alcanzó el tope de {max_pages} páginas de actividad sin encontrar el final. "
                "El histórico podría estar incompleto."
            )

        logger.info(f"Actividad de la liga: {len(todos)} movimientos en {len(crudos)} páginas.")
        return todos, crudos
