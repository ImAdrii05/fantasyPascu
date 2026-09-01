"""Reconstrucción del dinero y patrimonio de cada mánager de la liga.

POR QUÉ ESTE MÓDULO EXISTE
--------------------------
La API no expone la caja de los rivales: el campo `teamMoney` llega SIEMPRE a NULL
(verificado). La única vía es reconstruirla sumando cada movimiento desde que se creó
la liga, usando el histórico de actividad.

QUÉ ES EXACTO Y QUÉ ES ESTIMADO
-------------------------------
Si todos los fundadores partieron del mismo saldo inicial `S`, entonces para cada
mánager: caja = S + flujo_neto. De ahí se sigue algo importante:

  - EXACTO: la DIFERENCIA de caja entre dos mánagers, porque al restar `S` se cancela.
    "Fulano tiene 12,3 M más que Mengano" es un dato duro, no una estimación.
  - ESTIMADO: el valor ABSOLUTO de la caja, que depende de `S`.

`S` no aparece en ninguna respuesta de la API. Lo que sí se puede es acotarlo: la caja
nunca puede ser negativa, así que `S` es como mínimo el mayor descubierto que alcanza
cualquier mánager. Con los datos reales ese mínimo sale exactamente 115.000.000, una
cifra redonda que difícilmente es casualidad, y por eso se toma como valor por defecto.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable
import pandas as pd

# Saldo inicial de cada fundador. Configurable según reglas de cada liga.
SALDO_INICIAL_POR_DEFECTO = 115_000_000

# Saldo de quien se incorpora con la liga ya empezada (observado: 100M).
SALDO_INCORPORACION_TARDIA = 100_000_000

# Interpretación de cada activityTypeId según mecánica oficial de LaLiga Fantasy:
COMPRA_MERCADO = 31      # sale dinero: el mánager adquiere un jugador del mercado
VENTA_MERCADO = 33       # entra dinero: el mánager vende un jugador al mercado
PREMIO_JORNADA = 6       # entra dinero: premio semanal por puntos (trae weekNumber)
TRASPASO = (1, 2)        # entre dos mánagers: user1 paga, user2 cobra

# Tipos sin efecto económico: alineaciones, altas administrativas, etc.
TIPOS_SIN_DINERO = {9, 10, 13, 14, 15, 16, 17, 18, 19}


@dataclass
class ApunteContable:
    """Un movimiento de dinero de un mánager concreto, con su signo ya aplicado."""

    manager_id: str
    movement_id: str
    occurred_at: str
    activity_type: int
    concept: str
    signo_origen: str
    amount: int  # positivo entra, negativo sale
    player_id: str | None = None


@dataclass
class BalanceManager:
    """Situación económica reconstruida de un mánager."""

    manager_id: str
    flujo_neto: int = 0            # exacto: suma de todos sus movimientos
    caja_estimada: int = 0         # estimado: saldo_inicial + flujo_neto
    peor_descubierto: int = 0      # saldo mínimo alcanzado partiendo de cero
    num_movimientos: int = 0
    incorporacion_tardia: bool = False  # entró con la liga empezada
    apuntes: list[ApunteContable] = field(default_factory=list)


def clasificar(movimiento: Any) -> list[tuple[str, int, str, str]]:
    """Traduce un movimiento en los apuntes contables que genera.

    Returns:
        Lista de (manager_id, importe_con_signo, concepto, signo_origen).
    """
    amount = getattr(movimiento, "amount", None)
    if not amount:
        return []

    try:
        tipo = int(movimiento.movement_type)
    except (TypeError, ValueError):
        return []

    u1 = getattr(movimiento, "user1_id", None)
    u2 = getattr(movimiento, "user2_id", None)

    if tipo == VENTA_MERCADO and u1:
        return [(u1, +amount, "Venta al mercado", "venta_mercado")]

    if tipo == COMPRA_MERCADO and u1:
        return [(u1, -amount, "Compra en el mercado", "compra_mercado")]

    if tipo == PREMIO_JORNADA and u1:
        jornada = getattr(movimiento, "week_number", None)
        concepto = f"Premio de la jornada {jornada}" if jornada else "Premio de jornada"
        return [(u1, +amount, concepto, "premio_jornada")]

    if tipo in TRASPASO:
        apuntes = []
        if u1:
            apuntes.append((u1, -amount, "Fichaje a otro mánager", "traspaso_salida"))
        if u2:
            apuntes.append((u2, +amount, "Venta a otro mánager", "traspaso_entrada"))
        return apuntes

    return []


def detectar_flujos_desconocidos(movimientos: Iterable[Any]) -> dict[int, int]:
    """Busca tipos de actividad CON dinero no contemplados."""
    conocidos = {VENTA_MERCADO, COMPRA_MERCADO, PREMIO_JORNADA, *TRASPASO}
    desconocidos: dict[int, int] = defaultdict(int)

    for m in movimientos:
        amt = getattr(m, "amount", None)
        if not amt:
            continue
        try:
            tipo = int(m.movement_type)
        except (TypeError, ValueError):
            continue
        if tipo not in conocidos and tipo not in TIPOS_SIN_DINERO:
            desconocidos[tipo] += 1

    return dict(desconocidos)


def construir_balances(
    movimientos: Iterable[Any],
    saldo_inicial: int = SALDO_INICIAL_POR_DEFECTO,
    managers_conocidos: Iterable[str] | None = None,
) -> dict[str, BalanceManager]:
    """Reconstruye la situación económica de cada mánager desde el inicio de la liga."""
    ordenados = sorted(
        (m for m in movimientos if getattr(m, "movement_date", None)),
        key=lambda m: m.movement_date,
    )

    balances: dict[str, BalanceManager] = {}

    for m in ordenados:
        for manager_id, importe, concepto, signo_origen in clasificar(m):
            bal = balances.setdefault(manager_id, BalanceManager(manager_id=manager_id))
            bal.flujo_neto += importe
            bal.num_movimientos += 1
            bal.peor_descubierto = min(bal.peor_descubierto, bal.flujo_neto)
            bal.apuntes.append(
                ApunteContable(
                    manager_id=manager_id,
                    movement_id=str(getattr(m, "movement_id", "")),
                    occurred_at=str(m.movement_date),
                    activity_type=int(m.movement_type),
                    concept=concepto,
                    signo_origen=signo_origen,
                    amount=importe,
                    player_id=getattr(m, "player_id", None),
                )
            )

    # Registrar mánagers conocidos sin movimientos (incorporación tardía)
    for manager_id in managers_conocidos or ():
        balances.setdefault(
            str(manager_id), BalanceManager(manager_id=str(manager_id), incorporacion_tardia=True)
        )

    for bal in balances.values():
        if bal.num_movimientos == 0:
            bal.incorporacion_tardia = True
            bal.caja_estimada = SALDO_INCORPORACION_TARDIA
        else:
            bal.caja_estimada = saldo_inicial + bal.flujo_neto

    return balances


def saldo_inicial_minimo(movimientos: Iterable[Any]) -> int:
    """Calcula el saldo inicial más bajo que evita que alguien quede en negativo."""
    balances = construir_balances(movimientos, saldo_inicial=0)
    if not balances:
        return 0
    return -min(b.peor_descubierto for b in balances.values())


class _MovementAdapter:
    """Adaptador tolerante que lee campos normalizados con fallback al JSON crudo."""

    def __init__(self, row: dict[str, Any]):
        raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        self.movement_id = str(row.get("movement_id") or raw.get("id") or raw.get("activityId") or "")

        m_type = row.get("movement_type") if pd.notnull(row.get("movement_type")) else raw.get("activityTypeId")
        try:
            self.movement_type = int(m_type) if m_type is not None else None
        except (ValueError, TypeError):
            self.movement_type = None

        m_date = row.get("movement_date")
        if pd.notnull(m_date) and str(m_date).strip():
            self.movement_date = str(m_date).strip()
        else:
            self.movement_date = raw.get("createdAt") or raw.get("created") or raw.get("date") or ""

        amt = row.get("amount") if pd.notnull(row.get("amount")) else (raw.get("amount") or raw.get("money") or raw.get("price"))
        try:
            self.amount = int(amt) if amt is not None else None
        except (ValueError, TypeError):
            self.amount = None

        u1 = row.get("user1_id") if pd.notnull(row.get("user1_id")) else raw.get("user1Id")
        self.user1_id = str(u1).strip() if u1 is not None and str(u1).strip() else None

        u2 = row.get("user2_id") if pd.notnull(row.get("user2_id")) else raw.get("user2Id")
        self.user2_id = str(u2).strip() if u2 is not None and str(u2).strip() else None

        pid = row.get("player_id") if pd.notnull(row.get("player_id")) else (raw.get("playerMasterId") or raw.get("playerId"))
        self.player_id = str(pid).strip() if pid is not None and str(pid).strip() else None

        self.week_number = row.get("week_number") if pd.notnull(row.get("week_number")) else raw.get("weekNumber")


def calculate_estimated_cash(
    df_standings: pd.DataFrame,
    df_movements: pd.DataFrame,
    saldo_inicial: int = SALDO_INICIAL_POR_DEFECTO,
) -> pd.DataFrame:
    """Calcula la caja estimada para cada mánager a partir de DataFrames.

    Returns:
        DataFrame con columnas:
        ['team_id', 'manager_id', 'cash_estimate', 'net_transfer_flow', 'prize_flow', 'movements_count', 'is_late_join']
    """
    if df_movements is None or df_movements.empty:
        if df_standings is None or df_standings.empty:
            return pd.DataFrame(
                columns=["team_id", "manager_id", "cash_estimate", "net_transfer_flow", "prize_flow", "movements_count", "is_late_join"]
            )
        rows = []
        for _, s in df_standings.iterrows():
            tid = str(s.get("league_team_id") or "")
            mid = str(s.get("manager_id") or tid)
            rows.append({
                "team_id": tid,
                "manager_id": mid,
                "cash_estimate": saldo_inicial,
                "net_transfer_flow": 0,
                "prize_flow": 0,
                "movements_count": 0,
                "is_late_join": False,
            })
        return pd.DataFrame(rows)

    mov_objs = [_MovementAdapter(r) for _, r in df_movements.iterrows()]

    # Mapeo de manager_id <-> team_id
    mgr_to_team: dict[str, str] = {}
    team_to_mgr: dict[str, str] = {}
    known_managers: list[str] = []

    if df_standings is not None and not df_standings.empty:
        for _, s in df_standings.iterrows():
            tid = str(s.get("league_team_id") or "")
            mid = str(s.get("manager_id") or "")
            if mid and tid:
                mgr_to_team[mid] = tid
                team_to_mgr[tid] = mid
                known_managers.append(mid)
            elif tid:
                known_managers.append(tid)

    balances = construir_balances(
        mov_objs,
        saldo_inicial=saldo_inicial,
        managers_conocidos=known_managers if known_managers else None,
    )

    rows = []
    # Primero iterar por los mánagers de la clasificación si existen
    processed_managers = set()
    if df_standings is not None and not df_standings.empty:
        for _, s in df_standings.iterrows():
            tid = str(s.get("league_team_id") or "")
            mid = str(s.get("manager_id") or tid)
            bal = balances.get(mid) or balances.get(tid)
            processed_managers.add(mid)
            processed_managers.add(tid)

            if bal:
                net_transfer = sum(
                    a.amount for a in bal.apuntes if a.signo_origen in ("compra_mercado", "venta_mercado", "traspaso_salida", "traspaso_entrada")
                )
                prizes = sum(a.amount for a in bal.apuntes if a.signo_origen == "premio_jornada")
                caja = bal.caja_estimada
                mov_count = bal.num_movimientos
                late_join = bal.incorporacion_tardia
            else:
                net_transfer = 0
                prizes = 0
                caja = SALDO_INCORPORACION_TARDIA
                mov_count = 0
                late_join = True

            rows.append({
                "team_id": tid,
                "manager_id": mid,
                "cash_estimate": caja,
                "net_transfer_flow": net_transfer,
                "prize_flow": prizes,
                "movements_count": mov_count,
                "is_late_join": late_join,
            })

    # Añadir cualquier otro balance no emparejado
    for mgr_id, bal in balances.items():
        if mgr_id not in processed_managers:
            net_transfer = sum(
                a.amount for a in bal.apuntes if a.signo_origen in ("compra_mercado", "venta_mercado", "traspaso_salida", "traspaso_entrada")
            )
            prizes = sum(a.amount for a in bal.apuntes if a.signo_origen == "premio_jornada")
            rows.append({
                "team_id": mgr_to_team.get(mgr_id, mgr_id),
                "manager_id": mgr_id,
                "cash_estimate": bal.caja_estimada,
                "net_transfer_flow": net_transfer,
                "prize_flow": prizes,
                "movements_count": bal.num_movimientos,
                "is_late_join": bal.incorporacion_tardia,
            })

    return pd.DataFrame(rows)


def suggest_initial_balance(df_movements: pd.DataFrame) -> int:
    """Calcula el saldo inicial mínimo sugerido a partir de un DataFrame de movimientos."""
    if df_movements is None or df_movements.empty:
        return SALDO_INICIAL_POR_DEFECTO

    mov_objs = [_MovementAdapter(r) for _, r in df_movements.iterrows()]
    min_saldo = saldo_inicial_minimo(mov_objs)
    return max(min_saldo, SALDO_INICIAL_POR_DEFECTO)
