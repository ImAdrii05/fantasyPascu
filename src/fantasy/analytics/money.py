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
Sigue siendo una inferencia: cualquier cifra que dependa de `S` debe presentarse como
estimada, nunca como leída.

LÍMITE CONOCIDO
---------------
Si existen gastos que no se registran en la actividad (por ejemplo, subidas de cláusula
o blindajes), la reconstrucción se desviará de forma acumulativa. En los 209 eventos
analizados no hay ningún tipo con importe compatible con un blindaje, pero es un
supuesto no demostrado: `detectar_flujos_desconocidos()` vigila que no aparezcan tipos
de actividad nuevos con dinero que este módulo no sepa interpretar.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# Saldo inicial de cada fundador. NO es un dato leído de la API: es el mínimo que hace
# que ningún mánager quede en números rojos, calculado sobre el histórico real. Se deja
# como constante configurable porque una liga con otras reglas tendría otro valor.
SALDO_INICIAL_POR_DEFECTO = 115_000_000

# Saldo de quien se incorpora con la liga ya empezada. Este SÍ es un dato observado:
# es la caja real del usuario propio (visible vía `team.money` en el endpoint de ligas)
# recién entrado en la liga y sin ningún movimiento a sus espaldas. Es distinto del
# presupuesto fundacional, así que aplicar `SALDO_INICIAL_POR_DEFECTO` a un recién
# llegado le inflaría la caja en 15 millones.
SALDO_INCORPORACION_TARDIA = 100_000_000

# Interpretación de cada activityTypeId, DEDUCIDA DE LA MECÁNICA REAL siguiendo la
# cadena completa de un jugador, no de correlaciones ni de números que salen redondos.
#
# Ejemplo que lo fija (jugador 2354):
#   17 ago  tipo 31  u1=6211313                55.000.000  -> compra en el mercado
#   31 ago  tipo  1  u1=9867326 u2=6211313     59.360.561  -> u1 paga la cláusula a u2
#    1 sep  tipo 33  u1=9867326                51.152.468  -> vende al mercado
#
# Los eventos tipo 31 caen siempre a las 10:12, la hora de resolución del mercado.
COMPRA_MERCADO = 31      # sale dinero: el mánager adquiere un jugador
VENTA_MERCADO = 33       # entra dinero: el mánager se deshace de un jugador
PREMIO_JORNADA = 6       # entra dinero: premio semanal por puntos (trae weekNumber)
TRASPASO = (1, 2)        # entre dos mánagers: user1 paga, user2 cobra

# Tipos sin efecto económico: altas, alineaciones y demás eventos administrativos.
# Se enumeran explícitamente para poder distinguir "sé que esto no mueve dinero" de
# "ha aparecido un tipo que no conozco", que es justo lo que hay que detectar.
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

    Un traspaso genera DOS apuntes (quien paga y quien cobra); una operación de
    mercado, uno solo; un evento administrativo, ninguno.

    Returns:
        Lista de (manager_id, importe_con_signo, concepto, signo_origen).
    """
    amount = movimiento.amount
    if not amount:
        return []

    try:
        tipo = int(movimiento.movement_type)
    except (TypeError, ValueError):
        return []

    u1 = movimiento.user1_id
    u2 = movimiento.user2_id

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
    """Busca tipos de actividad CON dinero que este módulo no sabe interpretar.

    Es la alarma del sistema. Si LaLiga añade un tipo de movimiento con importe (unas
    subidas de cláusula, por ejemplo), sus euros se quedarían fuera del cálculo y todos
    los saldos se irían desviando en silencio. Mejor saberlo y decirlo.

    Returns:
        {activityTypeId: número de eventos} de los tipos con dinero no contemplados.
    """
    conocidos = {VENTA_MERCADO, COMPRA_MERCADO, PREMIO_JORNADA, *TRASPASO}
    desconocidos: dict[int, int] = defaultdict(int)

    for m in movimientos:
        if not m.amount:
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
    """Reconstruye la situación económica de cada mánager desde el inicio de la liga.

    Los movimientos se ordenan por fecha: el orden importa porque `peor_descubierto`
    solo tiene sentido recorriendo la historia en secuencia.

    Args:
        saldo_inicial: el `S` de la fórmula. Cambiarlo desplaza todas las cajas por
            igual y NO altera las diferencias entre mánagers, que siguen siendo exactas.
    """
    ordenados = sorted(
        (m for m in movimientos if m.movement_date),
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
                    movement_id=m.movement_id,
                    occurred_at=m.movement_date,
                    activity_type=int(m.movement_type),
                    concept=concepto,
                    signo_origen=signo_origen,
                    amount=importe,
                    player_id=m.player_id,
                )
            )

    # Un mánager de la liga sin un solo movimiento se incorporó con la liga empezada:
    # no tiene historia que reconstruir y su saldo es el de incorporación, no el
    # fundacional. Sin este caso, su caja saldría inflada.
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
    """Calcula el saldo inicial más bajo que evita que alguien quede en negativo.

    Es la única cota dura que tenemos sobre `S`. Si el resultado sube por encima del
    `SALDO_INICIAL_POR_DEFECTO`, la constante se ha quedado obsoleta y las cajas
    estimadas estarían mal: conviene revisarla en vez de seguir sumando.
    """
    balances = construir_balances(movimientos, saldo_inicial=0)
    if not balances:
        return 0
    return -min(b.peor_descubierto for b in balances.values())
