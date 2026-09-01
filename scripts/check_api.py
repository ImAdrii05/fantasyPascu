"""Script de diagnóstico para verificar conectividad y respuestas con la API de LaLiga Fantasy."""

from pathlib import Path
import sys

# Forzar UTF-8 en salida estándar si es posible en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Asegurar que src está en el path de importación
src_path = Path(__file__).resolve().parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fantasy.api.client import FantasyApiClient, FantasyApiError
from fantasy.auth.errors import AuthExpired
from fantasy import config


def main():
    print("=" * 60)
    print("DIAGNOSTICO DE CONECTIVIDAD CON API - LALIGA FANTASY")
    print("=" * 60)

    client = FantasyApiClient(throttle_seconds=0.5)

    # 1. Equipos maestros
    print("\n1. Consultando maestro de equipos...")
    try:
        teams, _ = client.get_teams_master()
        print(f"[OK] Equipos recibidos: {len(teams)}")
        if teams:
            sample = teams[0]
            print(f"     Ejemplo: ID={sample.id}, Nombre='{sample.name}', Short='{sample.short_name}', Slug='{sample.slug}'")
    except Exception as e:
        print(f"[X] Error al consultar equipos maestros: {e}")

    # 2. Listado de jugadores
    print("\n2. Consultando listado global de jugadores...")
    try:
        players, _ = client.get_all_players()
        print(f"[OK] Jugadores recibidos: {len(players)}")
        if players:
            sample = players[0]
            val_str = f"{sample.market_value:,} €" if sample.market_value is not None else "N/A"
            print(
                f"     Ejemplo: ID={sample.id}, Nombre='{sample.name}', Posicion='{sample.position}', "
                f"Valor={val_str}, Puntos={sample.points}"
            )
    except Exception as e:
        print(f"[X] Error al consultar jugadores: {e}")

    # 3. Liga privada (si está configurada)
    league_id = config.FANTASY_LEAGUE_ID
    if league_id:
        print(f"\n3. Consultando liga privada (ID: {league_id})...")
        try:
            standings, raw_standing = client.get_league_standing(league_id)
            print(f"[OK] Clasificacion recibida: {len(standings)} equipos.")
            if standings:
                top = standings[0]
                top_val = f"{top.team_value:,} €" if top.team_value is not None else "N/A"
                print(f"     Lider: {top.team_name} (Manager: {top.manager_name}) - {top.points} pts, Valor: {top_val}")

            movements, _ = client.get_league_activity(league_id)
            print(f"[OK] Movimientos recientes recibidos: {len(movements)}")
        except Exception as e:
            print(f"[X] Error al consultar datos de liga privada: {e}")
    else:
        print("\n3. Liga privada no configurada en FANTASY_LEAGUE_ID (omitida).")

    print("\n" + "=" * 60)
    print("DIAGNOSTICO FINALIZADO")
    print("=" * 60)


if __name__ == "__main__":
    main()
