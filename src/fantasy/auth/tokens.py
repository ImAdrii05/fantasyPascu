"""Modelo de datos para conjunto de tokens OAuth2 y cálculo de expiración."""

from dataclasses import dataclass, asdict
import time
from typing import Any


@dataclass
class TokenSet:
    """Representa el conjunto de tokens de autenticación de LaLiga / Azure B2C."""
    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None  # Timestamp Unix absoluto en segundos
    token_type: str = "Bearer"
    client_id: str | None = None

    def is_expired(self, margin_seconds: int = 300) -> bool:
        """Comprueba si el token ha expirado o expirará en menos del margen especificado (por defecto 5 minutos)."""
        if not self.expires_at:
            return True
        return (self.expires_at - int(time.time())) <= margin_seconds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenSet":
        """Construye un TokenSet a partir de una respuesta de API o JSON almacenado."""
        if not isinstance(data, dict):
            raise ValueError("Los datos del token deben ser un diccionario.")

        # En Azure B2C, si no hay access_token explícito, el id_token actúa como bearer
        access_token = data.get("access_token") or data.get("id_token") or ""
        id_token = data.get("id_token")
        refresh_token = data.get("refresh_token")
        token_type = data.get("token_type", "Bearer")
        client_id = data.get("client_id")

        # Calcular o extraer expires_at absoluto
        expires_at = data.get("expires_at")
        if expires_at is None:
            if "expires_on" in data:
                # expires_on ya suele ser un timestamp absoluto
                try:
                    expires_at = int(data["expires_on"])
                except (ValueError, TypeError):
                    expires_at = None
            elif "id_token_expires_in" in data:
                try:
                    expires_at = int(time.time()) + int(data["id_token_expires_in"])
                except (ValueError, TypeError):
                    expires_at = None
            elif "expires_in" in data:
                try:
                    expires_at = int(time.time()) + int(data["expires_in"])
                except (ValueError, TypeError):
                    expires_at = None

        return cls(
            access_token=str(access_token),
            id_token=str(id_token) if id_token else None,
            refresh_token=str(refresh_token) if refresh_token else None,
            expires_at=expires_at,
            token_type=str(token_type),
            client_id=str(client_id) if client_id else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convierte el TokenSet en un diccionario listo para serializar a JSON."""
        return asdict(self)
