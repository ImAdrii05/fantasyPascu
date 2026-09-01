"""Almacenamiento y persistencia de tokens (Fichero local, Variables de entorno y Supabase)."""

from abc import ABC, abstractmethod
import json
import logging
import os
from pathlib import Path
from typing import Any

from fantasy.auth.errors import AuthConfigMissing
from fantasy.auth.tokens import TokenSet
from fantasy import config

logger = logging.getLogger(__name__)


class BaseTokenStore(ABC):
    """Interfaz abstracta para el almacenamiento de tokens."""

    @abstractmethod
    def load(self) -> TokenSet | None:
        """Carga el TokenSet almacenado, o None si no existe."""
        pass

    @abstractmethod
    def save(self, tokens: TokenSet) -> None:
        """Persiste el TokenSet."""
        pass


class FileTokenStore(BaseTokenStore):
    """Almacén basado en archivo JSON local (típicamente secrets/token.json)."""

    def __init__(self, file_path: str | Path | None = None):
        self.file_path = Path(file_path or config.FANTASY_TOKEN_PATH)

    def load(self) -> TokenSet | None:
        if not self.file_path.exists():
            return None
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TokenSet.from_dict(data)
        except Exception as e:
            logger.warning(f"Error al leer token desde archivo {self.file_path}: {e}")
            return None

    def save(self, tokens: TokenSet) -> None:
        # Asegurar que el directorio padre existe
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(tokens.to_dict(), f, indent=2, ensure_ascii=False)
        logger.debug(f"TokenSet guardado en archivo {self.file_path}")


class EnvTokenStore(BaseTokenStore):
    """Almacén basado en variable de entorno (utilizado en CI al arrancar)."""

    def __init__(self, raw_json: str | None = None):
        self.raw_json = raw_json or config.FANTASY_TOKEN_JSON
        self._cached: TokenSet | None = None

    def load(self) -> TokenSet | None:
        if self._cached:
            return self._cached
        if not self.raw_json:
            return None
        try:
            data = json.loads(self.raw_json)
            self._cached = TokenSet.from_dict(data)
            return self._cached
        except Exception as e:
            logger.warning(f"Error al parsear FANTASY_TOKEN_JSON: {e}")
            return None

    def save(self, tokens: TokenSet) -> None:
        # En memoria solo; las variables de entorno del proceso no persisten tras finalizar
        self._cached = tokens
        logger.debug("TokenSet actualizado en memoria (EnvTokenStore)")


class SupabaseTokenStore(BaseTokenStore):
    """Almacén persistente en la tabla `auth_state` de Supabase (garantiza rotación de refresh_token en CI)."""

    def __init__(self, supabase_client: Any = None):
        self._client = supabase_client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
            return None
        try:
            from supabase import create_client
            self._client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
            return self._client
        except Exception as e:
            logger.warning(f"No se pudo inicializar cliente Supabase para token store: {e}")
            return None

    def load(self) -> TokenSet | None:
        client = self._get_client()
        if not client:
            return None
        try:
            res = client.table("auth_state").select("tokens").eq("id", "primary").execute()
            if res.data and len(res.data) > 0 and res.data[0].get("tokens"):
                return TokenSet.from_dict(res.data[0]["tokens"])
        except Exception as e:
            logger.warning(f"No se pudo cargar token desde Supabase (auth_state): {e}")
        return None

    def save(self, tokens: TokenSet) -> None:
        client = self._get_client()
        if not client:
            return
        try:
            payload = {
                "id": "primary",
                "tokens": tokens.to_dict(),
                "updated_at": "now()",
            }
            client.table("auth_state").upsert(payload).execute()
            logger.info("TokenSet persistido exitosamente en Supabase (auth_state).")
        except Exception as e:
            logger.warning(f"Error al guardar token en Supabase (auth_state): {e}")


class HybridTokenStore(BaseTokenStore):
    """Combina almacenamiento local y remoto según disponibilidad (prioridad CI -> Supabase -> Env; Local -> File)."""

    def __init__(
        self,
        file_store: FileTokenStore | None = None,
        env_store: EnvTokenStore | None = None,
        supabase_store: SupabaseTokenStore | None = None,
    ):
        self.file_store = file_store or FileTokenStore()
        self.env_store = env_store or EnvTokenStore()
        self.supabase_store = supabase_store or SupabaseTokenStore()

    def load(self) -> TokenSet | None:
        # 1. Si estamos en CI o Supabase está configurado, consultar Supabase primero (tiene el refresh rotado más reciente)
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            supa_token = self.supabase_store.load()
            if supa_token:
                logger.debug("Token cargado desde Supabase auth_state")
                return supa_token

        # 2. Si hay variable de entorno (bootstrap en CI)
        env_token = self.env_store.load()
        if env_token:
            logger.debug("Token cargado desde FANTASY_TOKEN_JSON")
            # Sembrar en Supabase si está disponible
            if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
                self.supabase_store.save(env_token)
            return env_token

        # 3. Fallback a fichero local
        file_token = self.file_store.load()
        if file_token:
            logger.debug(f"Token cargado desde archivo local {self.file_store.file_path}")
            return file_token

        return None

    def save(self, tokens: TokenSet) -> None:
        # Guardar en todos los destinos disponibles
        self.env_store.save(tokens)
        if self.file_store.file_path.exists() or not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
            try:
                self.file_store.save(tokens)
            except Exception as e:
                logger.warning(f"No se pudo guardar token en archivo local: {e}")

        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            self.supabase_store.save(tokens)


_default_store: BaseTokenStore | None = None


def get_token_store() -> BaseTokenStore:
    """Devuelve la instancia singleton del almacén de tokens configurado."""
    global _default_store
    if _default_store is None:
        _default_store = HybridTokenStore()
    return _default_store


def set_token_store(store: BaseTokenStore) -> None:
    """Permite sobreescribir el almacén de tokens (utilizado principalmente en tests)."""
    global _default_store
    _default_store = store
