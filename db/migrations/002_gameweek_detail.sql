-- =============================================================================
-- Migración 002: estadísticas detalladas por jornada
--
-- El listado global de jugadores solo trae puntos por jornada (`weekPoints`).
-- Los minutos y el resto de estadísticas viven en el detalle de cada jugador,
-- bajo `playerMaster.playerStats[].stats`, donde cada métrica es un par
-- [valor, puntos] (ej. "mins_played": [90, 2]).
--
-- Se guardan las métricas principales en columnas propias (consultables con SQL
-- cómodo) y ADEMÁS el diccionario completo en `stats` como JSONB, para no perder
-- nada el día que queramos una métrica que hoy no estamos mirando: el histórico
-- no se puede recuperar hacia atrás.
-- =============================================================================

ALTER TABLE player_gameweek_stats
    ADD COLUMN IF NOT EXISTS second_yellow_cards INTEGER,
    ADD COLUMN IF NOT EXISTS own_goals           INTEGER,
    ADD COLUMN IF NOT EXISTS saves               INTEGER,
    ADD COLUMN IF NOT EXISTS goals_conceded      INTEGER,
    ADD COLUMN IF NOT EXISTS stats               JSONB;

COMMENT ON COLUMN player_gameweek_stats.stats IS
    'Diccionario completo de estadísticas de la jornada tal cual lo devuelve la API, '
    'con cada métrica como par [valor, puntos]. Fuente de verdad para métricas futuras.';

CREATE INDEX IF NOT EXISTS idx_player_gameweek_stats_gw ON player_gameweek_stats(gameweek);

-- =============================================================================
-- Índices de claves foráneas que faltaban.
--
-- Postgres NO indexa automáticamente las columnas de clave foránea. Sin estos
-- índices, dos de las consultas más frecuentes de la app hacen escaneo completo:
--   - "todos los jugadores de este equipo"        -> players.team_id
--   - "historial de movimientos de este jugador"  -> league_movements.player_id
-- Además, sin índice en la FK, borrar un equipo o un jugador bloquea y recorre
-- la tabla hija entera para resolver el ON DELETE.
--
-- Se crean ahora, con las tablas casi vacías, porque hacerlo con meses de
-- histórico dentro es mucho más lento.
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_league_movements_player ON league_movements(player_id);
