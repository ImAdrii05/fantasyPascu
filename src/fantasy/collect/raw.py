"""Persistencia de respuestas crudas (JSON) para preservar la fidelidad del histórico."""

import logging
from typing import Any
from fantasy.store.supabase import SupabaseStore, get_supabase_store

logger = logging.getLogger(__name__)


def persist_raw(endpoint: str, payload: Any, store: SupabaseStore | None = None) -> None:
    """Guarda el JSON crudo en la tabla raw_snapshots antes de cualquier parseo o normalización.

    Esto garantiza que si el modelo de datos cambia o la normalización falla,
    el dato original de la jornada no se pierde y sigue disponible para reprocesamiento.
    """
    target_store = store or get_supabase_store()
    try:
        target_store.save_raw_snapshot(endpoint=endpoint, payload=payload)
    except Exception as e:
        logger.error(f"Error crítico al persistir snapshot crudo de '{endpoint}': {e}")
        # Re-lanzar para no continuar a ciegas si falla la persistencia base
        raise
