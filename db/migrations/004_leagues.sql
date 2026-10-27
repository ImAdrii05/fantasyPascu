-- =============================================================================
-- Migración 004: ligas del usuario
--
-- Con el login interactivo el job ya no necesita FANTASY_LEAGUE_ID: detecta todas
-- las ligas de la cuenta y recolecta cada una. Las tablas de liga ya llevan
-- `league_id`, pero solo el ID; esta tabla guarda el nombre para que el dashboard
-- pueda ofrecer un selector legible en vez de números.
--
-- `team_money` es el saldo PROPIO (el único que da la API). El de los rivales
-- sigue sin existir: ver la nota de league_standings en 001_init.sql.
-- =============================================================================
CREATE TABLE IF NOT EXISTS leagues (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    team_id     TEXT,
    team_money  BIGINT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE leagues ENABLE ROW LEVEL SECURITY;
