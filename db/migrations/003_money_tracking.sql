-- =============================================================================
-- Migración 003: bases para el seguimiento de dinero y patrimonio
--
-- La API NO expone el saldo en caja de los rivales (`teamMoney` llega siempre a
-- NULL). La única vía es reconstruirlo sumando cada movimiento desde el inicio de
-- la liga. Para eso hacen falta dos cosas que hasta ahora no guardábamos:
--
--   1. El `managerId` en la clasificación. La actividad identifica a las personas
--      por managerId, mientras que la clasificación usa league_team_id. Sin esta
--      columna no se pueden cruzar las dos tablas, y sin cruzarlas no se sabe de
--      quién es cada euro.
--   2. Los usuarios implicados en cada movimiento. `from_team_id`/`to_team_id`
--      nunca se rellenan: la actividad real trae `user1Id` y `user2Id`, que son
--      managerIds. En un traspaso aparecen los dos; contra el mercado, solo user1.
-- =============================================================================

ALTER TABLE league_standings
    ADD COLUMN IF NOT EXISTS manager_id TEXT;

COMMENT ON COLUMN league_standings.manager_id IS
    'managerId, la clave que une esta tabla con league_movements.user1_id/user2_id.';

CREATE INDEX IF NOT EXISTS idx_league_standings_manager ON league_standings(manager_id);

ALTER TABLE league_movements
    ADD COLUMN IF NOT EXISTS user1_id    TEXT,
    ADD COLUMN IF NOT EXISTS user2_id    TEXT,
    ADD COLUMN IF NOT EXISTS week_number INTEGER;

CREATE INDEX IF NOT EXISTS idx_league_movements_user1 ON league_movements(user1_id);
CREATE INDEX IF NOT EXISTS idx_league_movements_user2 ON league_movements(user2_id);

-- =============================================================================
-- Libro mayor: una fila por cada movimiento de dinero de cada mánager.
--
-- Se guarda el resultado del cálculo, no solo el saldo final, para que cualquier
-- cifra sea auditable: se puede ver POR QUÉ alguien tiene el dinero que tiene.
-- Si un día el saldo parece raro, se mira aquí en vez de creerse el número.
--
-- `signo_origen` documenta la regla aplicada (ej. 'compra_mercado', 'venta_mercado',
-- 'traspaso_entrada'), de modo que un cambio de interpretación sea rastreable.
-- =============================================================================
CREATE TABLE IF NOT EXISTS manager_ledger (
    league_id      TEXT NOT NULL,
    manager_id     TEXT NOT NULL,
    movement_id    TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    activity_type  INTEGER,
    concept        TEXT NOT NULL,
    signo_origen   TEXT NOT NULL,
    amount         BIGINT NOT NULL,      -- con signo: positivo entra, negativo sale
    player_id      TEXT,
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (league_id, manager_id, movement_id)
);

CREATE INDEX IF NOT EXISTS idx_manager_ledger_manager ON manager_ledger(league_id, manager_id, occurred_at);

-- =============================================================================
-- Balance reconstruido por mánager y día.
--
-- `discrepancy` es la pieza clave de honestidad del sistema: el saldo se valida
-- contra el único dato real disponible (la caja del usuario propio, que sí es
-- visible). Si la reconstrucción no cuadra, la diferencia se guarda aquí y el
-- dashboard la muestra junto a la cifra. Nunca se presenta un saldo estimado como
-- si fuera exacto.
-- =============================================================================
CREATE TABLE IF NOT EXISTS manager_balance (
    snapshot_date  DATE NOT NULL,
    league_id      TEXT NOT NULL,
    manager_id     TEXT NOT NULL,
    manager_name   TEXT,
    cash           BIGINT,          -- caja reconstruida
    team_value     BIGINT,          -- valor de plantilla (dato real de la API)
    net_worth      BIGINT,          -- patrimonio = cash + team_value
    is_validated   BOOLEAN NOT NULL DEFAULT FALSE,
    discrepancy    BIGINT,          -- descuadre detectado; NULL si no se pudo medir
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, league_id, manager_id)
);

COMMENT ON COLUMN manager_balance.discrepancy IS
    'Euros que la reconstrucción no logra explicar. 0 = cuadra al euro. '
    'Debe mostrarse SIEMPRE junto a `cash`: un saldo sin su descuadre es un dato engañoso.';

ALTER TABLE manager_ledger  ENABLE ROW LEVEL SECURITY;
ALTER TABLE manager_balance ENABLE ROW LEVEL SECURITY;
