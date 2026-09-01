-- =============================================================================
-- Migración 001: Esquema inicial para LaLiga Fantasy
-- Base de datos privada: RLS habilitado en todas las tablas sin políticas públicas.
-- Acceso exclusivo mediante service_role key.
-- =============================================================================

-- 1. Tabla de Equipos maestros
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT,
    slug TEXT,
    badge_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Tabla de Jugadores (datos dimensionales)
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    nickname TEXT,
    slug TEXT,
    position TEXT,
    position_id INTEGER,
    team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
    status TEXT,
    image_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Snapshots diarios de Jugadores (TABLA CLAVE PARA SERIES TEMPORALES)
-- PK compuesta (snapshot_date, player_id) garantiza idempotencia diaria
CREATE TABLE IF NOT EXISTS player_daily (
    snapshot_date DATE NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    market_value BIGINT,
    points INTEGER,
    average_points NUMERIC(6, 2),
    played_matches INTEGER,
    minutes_played INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, player_id)
);

CREATE INDEX IF NOT EXISTS idx_player_daily_player ON player_daily(player_id);
CREATE INDEX IF NOT EXISTS idx_player_daily_date ON player_daily(snapshot_date);

-- 4. Estadísticas por Jornada de Jugador
CREATE TABLE IF NOT EXISTS player_gameweek_stats (
    player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    gameweek INTEGER NOT NULL,
    points INTEGER,
    minutes INTEGER,
    goals INTEGER,
    assists INTEGER,
    yellow_cards INTEGER,
    red_cards INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, gameweek)
);

-- 5. Clasificación y estado de la Liga Privada
-- NOTA (VERIFICADO contra la API real, no es una suposición):
-- El endpoint de clasificación SÍ incluye un campo `teamMoney`, pero llega SIEMPRE
-- a NULL para los rivales. En el equipo propio la clave ni siquiera aparece; el saldo
-- propio se obtiene por otra vía (campo `team.money` del endpoint de ligas del usuario).
-- Conclusión: NO disponemos del dinero líquido de los rivales, solo de `teamValue`,
-- puntos y movimientos. No estimar ni inferir el saldo ajeno a partir de esos datos.
CREATE TABLE IF NOT EXISTS league_standings (
    snapshot_date DATE NOT NULL,
    league_team_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    team_name TEXT NOT NULL,
    manager_name TEXT,
    team_value BIGINT,
    points INTEGER,
    position INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, league_team_id)
);

CREATE INDEX IF NOT EXISTS idx_league_standings_league ON league_standings(league_id);

-- 6. Mercado diario de la Liga Privada
CREATE TABLE IF NOT EXISTS league_market (
    snapshot_date DATE NOT NULL,
    league_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    player_id TEXT REFERENCES players(id) ON DELETE CASCADE,
    price BIGINT,
    owner_team_id TEXT,
    expires_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, league_id, market_id)
);

CREATE INDEX IF NOT EXISTS idx_league_market_league ON league_market(league_id);
CREATE INDEX IF NOT EXISTS idx_league_market_player ON league_market(player_id);

-- 7. Historial de movimientos de mercado y actividad de la liga
CREATE TABLE IF NOT EXISTS league_movements (
    movement_id TEXT PRIMARY KEY,
    league_id TEXT NOT NULL,
    player_id TEXT REFERENCES players(id) ON DELETE SET NULL,
    player_name TEXT,
    from_team_id TEXT,
    to_team_id TEXT,
    amount BIGINT,
    movement_type TEXT,
    movement_date TIMESTAMPTZ,
    raw_payload JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_league_movements_league ON league_movements(league_id);
CREATE INDEX IF NOT EXISTS idx_league_movements_date ON league_movements(movement_date);

-- 8. Snapshots crudos en JSONB (preserva el 100% de la información original antes de normalizar)
CREATE TABLE IF NOT EXISTS raw_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    endpoint TEXT NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_date_endpoint ON raw_snapshots(snapshot_date, endpoint);

-- 9. Almacén de estado de autenticación (persistencia del refresh_token rotado en CI)
CREATE TABLE IF NOT EXISTS auth_state (
    id TEXT PRIMARY KEY DEFAULT 'primary',
    tokens JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- SEGURIDAD: Habilitar RLS en todas las tablas sin políticas públicas.
-- La clave 'anon' pública no tendrá acceso a ninguna fila; solo 'service_role'.
-- =============================================================================
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE players ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_gameweek_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_standings ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_market ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_state ENABLE ROW LEVEL SECURITY;
