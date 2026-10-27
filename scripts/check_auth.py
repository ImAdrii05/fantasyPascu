"""Script de diagnóstico para verificar el estado de autenticación y caducidad del token."""

import datetime
from pathlib import Path
import sys

# Forzar UTF-8 en salida estándar si es posible en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Asegurar que src está en el path de importación
src_path = Path(__file__).resolve().parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fantasy.auth import get_access_token
from fantasy.auth.store import get_token_store
from fantasy.auth.errors import AuthExpired, AuthBackendChanged, AuthConfigMissing


def main():
    print("=" * 60)
    print("DIAGNOSTICO DE AUTENTICACION - LALIGA FANTASY")
    print("=" * 60)

    store = get_token_store()
    current_tokens = store.load()

    if not current_tokens:
        print("[X] No se encontro ningun token configurado.")
        print("    Inicia sesion con: python scripts/login.py (Apple, Google o email).")
        print("    Consulta README.md seccion 'Inicio de sesion' para ver las alternativas.")
        sys.exit(1)

    print(f"[*] Almacen de token detectado: {store.__class__.__name__}")
    if current_tokens.expires_at:
        exp_dt = datetime.datetime.fromtimestamp(current_tokens.expires_at)
        print(f"[*] Caducidad registrada: {exp_dt.strftime('%Y-%m-%d %H:%M:%S')} (timestamp: {current_tokens.expires_at})")
        print(f"[*] Expirado actualmente: {'SI' if current_tokens.is_expired() else 'NO'}")
    else:
        print("[!] No hay timestamp de expiracion registrado.")

    print("\nVerificando / Refrescando token...")
    try:
        token = get_access_token(force_refresh=False)
        masked_token = f"...{token[-6:]}" if len(token) >= 6 else "***"
        print(f"[OK] Token de acceso valido obtenido.")
        print(f"[*] Token (ultimos 6 caracteres): {masked_token}")
        print("[OK] Autenticacion operativa para realizar llamadas a la API.")
    except AuthExpired as e:
        print(f"[X] Error de autenticacion: {e}")
        sys.exit(1)
    except AuthBackendChanged as e:
        print(f"[X] Respuesta inesperada del backend B2C: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[X] Error inesperado: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
