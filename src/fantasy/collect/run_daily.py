"""Orquestador principal del snapshot diario de LaLiga Fantasy.

Ejecuta los sub-jobs con aislamiento de fallos:
- Si el sub-job global de jugadores tiene éxito pero la liga privada falla,
  el proceso finaliza en éxito parcial (código de salida 0) con avisos en el log.
- Solo si falla el cimiento (mercado global de jugadores), el proceso devuelve código de salida 1.
"""

from datetime import datetime
import logging
import sys
import time

from fantasy.api.client import FantasyApiClient
from fantasy.api.models import League
from fantasy.collect.players import collect_players
from fantasy.collect.league import collect_league
from fantasy.collect.raw import persist_raw
from fantasy.store.supabase import SupabaseStore, get_supabase_store
from fantasy import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fantasy.collect.daily")


def resolve_leagues(api_client: FantasyApiClient, store: SupabaseStore, errors: list[str]) -> list[League]:
    """Ligas a recolectar: las de FANTASY_LEAGUE_ID o, si está vacío, todas las de la cuenta.

    Las ligas del usuario se piden siempre, aunque haya IDs fijados: es una sola
    petición y es la que trae los nombres. Si falla y hay IDs fijados, se sigue con
    ellos; si falla y no los hay, no hay ligas que recolectar (y queda registrado).
    """
    fixed_ids = config.configured_league_ids()
    try:
        user_leagues, raw = api_client.get_user_leagues()
    except Exception as e:
        msg = f"No se pudieron obtener las ligas de la cuenta: {e}"
        logger.warning(msg, exc_info=True)
        errors.append(msg)
        return [League(id=league_id, name=f"Liga {league_id}") for league_id in fixed_ids]

    try:
        persist_raw("user_leagues", raw, store=store)
    except Exception as e:
        logger.warning(f"No se pudo guardar el JSON crudo de las ligas: {e}")

    if fixed_ids:
        by_id = {league.id: league for league in user_leagues}
        leagues = [by_id.get(league_id) or League(id=league_id, name=f"Liga {league_id}") for league_id in fixed_ids]
    else:
        leagues = user_leagues
        logger.info(f"FANTASY_LEAGUE_ID vacío: detectadas {len(leagues)} ligas en la cuenta.")

    try:
        store.upsert_leagues(leagues)
    except Exception as e:
        # Sin la migración 004 la tabla no existe. No impide recolectar: solo deja el
        # dashboard sin nombres de liga.
        logger.warning(f"No se pudieron guardar las ligas (¿falta la migración 004_leagues.sql?): {e}")

    return leagues


# Marca que se guarda en raw_snapshots al terminar un día SIN errores. Con ella, las
# ejecuciones siguientes del mismo día (hay varias programadas, por si alguna llega
# tarde o el mercado aún no estaba) terminan en segundos en vez de repetirlo todo.
MARCA_DIA_COMPLETO = "run_daily_ok"

# Fracción mínima de jugadores con valor distinto al de ayer para dar el mercado por
# recalculado. Cuando LaLiga ya lo ha hecho cambian muchos; si no, ninguno.
UMBRAL_MERCADO_ACTUALIZADO = 0.01


def mercado_actualizado(
    nuevos: dict[str, int | None],
    anteriores: dict[str, int | None],
    umbral: float = UMBRAL_MERCADO_ACTUALIZADO,
) -> bool:
    """¿Ha recalculado ya LaLiga el mercado de hoy?

    Compara el valor de cada jugador con el del último snapshot guardado. Sin
    referencia (primer día) no se puede saber, y se da por bueno.
    """
    comunes = [
        pid for pid, valor in nuevos.items()
        if valor is not None and anteriores.get(pid) is not None
    ]
    if not comunes:
        return True
    cambiados = sum(1 for pid in comunes if nuevos[pid] != anteriores[pid])
    return cambiados / len(comunes) >= umbral


def decidir_recoleccion(
    store, api_client, hoy: str, ahora_local: datetime, forzar: bool = False
) -> tuple[bool, str]:
    """Decide si esta ejecución debe recolectar. Devuelve (recolectar, motivo).

    - El día ya está completo -> no (salvo `forzar`).
    - Antes de la hora límite y con el mercado idéntico al de ayer -> no: LaLiga aún
      no lo ha recalculado, y guardarlo pondría a cero todas las subidas de hoy.
    - En cualquier otro caso -> sí.
    """
    if forzar:
        return True, "forzado a mano"
    if store.has_raw_snapshot(MARCA_DIA_COMPLETO, hoy):
        return False, f"el día {hoy} ya está completo"
    if ahora_local.hour >= config.HORA_LIMITE_ESPERA_MERCADO:
        return True, f"pasadas las {config.HORA_LIMITE_ESPERA_MERCADO}:00 se recolecta siempre"

    jugadores, _ = api_client.get_all_players()
    nuevos = {p.id: p.market_value for p in jugadores if p.id}
    if mercado_actualizado(nuevos, store.get_previous_market_values(hoy)):
        return True, "el mercado de hoy ya está recalculado"
    return False, "LaLiga aún no ha recalculado el mercado (valores idénticos a los de ayer)"


def run_daily() -> int:
    """Ejecuta el ciclo de recolección diario de snapshots.

    Returns:
        int: 0 en caso de éxito total o éxito parcial, 1 si falla el mercado global.
    """
    start_time = time.time()
    ahora_local = config.ahora_juego()
    today = ahora_local.date().isoformat()
    logger.info(f"============================================================")
    logger.info(f"INICIANDO SNAPSHOT DIARIO LA LIGA FANTASY - FECHA: {today} ({ahora_local:%H:%M} en España)")
    logger.info(f"============================================================")

    api_client = FantasyApiClient(throttle_seconds=0.5, max_retries=3)
    store = get_supabase_store()

    try:
        recolectar, motivo = decidir_recoleccion(
            store, api_client, today, ahora_local, forzar=config.FORZAR_SNAPSHOT
        )
    except Exception as e:
        # Decidir es solo un atajo: si no se puede (Supabase o la API fallan un
        # momento), se recolecta como siempre y el error real, si lo hay, sale abajo.
        logger.warning(f"No se pudo comprobar si hacía falta recolectar: {e}", exc_info=True)
        recolectar, motivo = True, "no se pudo comprobar, se recolecta por si acaso"
    if not recolectar:
        logger.info(f"⏭️ No se recolecta: {motivo}. Lo hará la siguiente ejecución programada.")
        return 0
    logger.info(f"Se recolecta: {motivo}.")

    summary: dict[str, int] = {
        "teams": 0,
        "players": 0,
        "player_daily": 0,
        "player_gameweek_stats": 0,
        "league_market": 0,
        "league_standings": 0,
        "league_movements": 0,
    }
    errors: list[str] = []
    players_success = False

    leagues = resolve_leagues(api_client, store, errors)
    for league in leagues:
        logger.info(f"  • Liga {league.id}: {league.name}")

    # SUB-JOB 1: Jugadores y mercado global (CIMIENTO PRINCIPAL)
    logger.info("--- [1/2] Recolección Global de Jugadores y Equipos ---")
    try:
        player_counts = collect_players(
            api_client=api_client,
            store=store,
            snapshot_date=today,
            # El detalle (minutos y stats finas) exige un league_id: el endpoint lo pide.
            # Los datos del jugador no dependen de la liga, así que basta con una.
            league_id=leagues[0].id if leagues else None,
        )
        summary.update(player_counts)
        players_success = True
        logger.info("✅ Sub-job de jugadores completado correctamente.")
    except Exception as e:
        err_msg = f"Fallo crítico en recolección global de jugadores: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

    # SUB-JOB 2: Ligas Privadas (Clasificación, Movimientos y Mercado), una a una:
    # el fallo de una liga no impide recolectar las demás.
    for league in leagues:
        logger.info(f"--- [2/2] Recolección de Liga Privada {league.name} (ID: {league.id}) ---")
        try:
            league_counts = collect_league(
                league_id=league.id,
                api_client=api_client,
                store=store,
                snapshot_date=today,
            )
            for key, value in league_counts.items():
                summary[key] += value
            logger.info(f"✅ Liga {league.name} completada correctamente.")
        except Exception as e:
            warn_msg = f"Fallo en recolección de liga privada {league.id}: {e}"
            logger.warning(warn_msg, exc_info=True)
            errors.append(warn_msg)
    if not leagues:
        logger.info("ℹ️ No hay ligas que recolectar. Omitiendo recolección de liga privada.")

    # RESUMEN FINAL
    elapsed = time.time() - start_time
    logger.info(f"============================================================")
    logger.info(f"RESUMEN DE EJECUCIÓN (Tiempo transcurrido: {elapsed:.2f}s)")
    logger.info(f"============================================================")
    for k, v in summary.items():
        logger.info(f"  • {k:<18}: {v:>5} filas")

    if errors:
        logger.info("------------------------------------------------------------")
        logger.info("INCIDENCIAS REGISTRADAS:")
        for err in errors:
            logger.warning(f"  ⚠️ {err}")

    if not players_success:
        logger.error("❌ LA RECOLECCIÓN GLOBAL FALLÓ. Saliendo con código de error 1.")
        return 1

    if errors:
        # Sin marca: la siguiente ejecución del día lo vuelve a intentar entero.
        logger.warning("⚠️ RECOLECCIÓN FINALIZADA CON ÉXITO PARCIAL (datos globales guardados).")
    else:
        try:
            persist_raw(MARCA_DIA_COMPLETO, {"resumen": summary, "segundos": round(elapsed, 1)}, store=store)
        except Exception as e:
            logger.warning(f"No se pudo guardar la marca de día completo: {e}")
        logger.info("🎉 RECOLECCIÓN FINALIZADA CON ÉXITO TOTAL.")

    return 0


if __name__ == "__main__":
    sys.exit(run_daily())
