"""Inicia sesión en LaLiga Fantasy (Apple, Google o email) y muestra tus ligas.

Uso:
    python scripts/login.py            # abre una ventana de navegador (requiere Playwright)
    python scripts/login.py --manual   # usa tu navegador y pegas la URL de vuelta

Sustituye a la captura manual del token desde DevTools: guarda los tokens en
secrets/token.json y, si Supabase está configurado, en `auth_state`, que es de donde
los lee el cron de GitHub Actions.
"""

import argparse
from pathlib import Path
import sys

# Forzar UTF-8 en salida estándar si es posible en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Asegurar que src está en el path de importación
src_path = Path(__file__).resolve().parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fantasy import config
from fantasy.api.client import FantasyApiClient
from fantasy.auth.errors import AuthBackendChanged, LoginFailed
from fantasy.auth.login import DEFAULT_TIMEOUT_SECONDS, login, save_login_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description="Login en LaLiga Fantasy y detección de ligas.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="No abrir ventana automatizada: abre tu navegador y pega la URL authredirect://",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Segundos para completar el login en la ventana (por defecto {DEFAULT_TIMEOUT_SECONDS}).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LOGIN - LALIGA FANTASY")
    print("=" * 60)
    if not args.manual:
        print("Se abrirá una ventana con la página de login de LaLiga.")
        print("Elige 'Continuar con Apple' (o Google, o email) e inicia sesión.")
        print("La ventana se cerrará sola al terminar.\n")

    try:
        tokens = login(manual=args.manual, timeout_seconds=args.timeout)
    except (LoginFailed, AuthBackendChanged) as e:
        print(f"[X] {e}")
        return 1

    try:
        destinations = save_login_tokens(tokens)
    except Exception as e:
        print(f"[X] Login correcto, pero no se pudieron guardar los tokens: {e}")
        return 1
    print("[OK] Sesión iniciada. Tokens guardados en: " + ", ".join(destinations))

    print("\nBuscando tus ligas...")
    client = FantasyApiClient(throttle_seconds=0.5)
    try:
        leagues, _ = client.get_user_leagues()
    except Exception as e:
        print(f"[X] No se pudieron obtener las ligas: {e}")
        return 1

    if not leagues:
        print("[!] La cuenta no participa en ninguna liga.")
        return 0

    print(f"[OK] {len(leagues)} liga(s):")
    for league in leagues:
        money = f" | tu saldo: {league.team_money:,} €" if league.team_money is not None else ""
        print(f"     - {league.name} (ID: {league.id}){money}")

    if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
        try:
            from fantasy.store.supabase import get_supabase_store

            get_supabase_store().upsert_leagues(leagues)
        except Exception as e:
            print(f"[!] No se pudieron guardar las ligas en Supabase (¿falta la migración 004?): {e}")

    fixed = config.configured_league_ids()
    if fixed:
        print(f"\nFANTASY_LEAGUE_ID limita el job diario a: {', '.join(fixed)}.")
        print("Déjalo vacío para que recolecte todas las ligas de arriba.")
    else:
        print("\nEl job diario recolectará todas estas ligas (FANTASY_LEAGUE_ID está vacío).")
        print("Para limitarlo, pon FANTASY_LEAGUE_ID=id1,id2 en .env o en los secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
