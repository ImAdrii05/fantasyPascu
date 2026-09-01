"""Tests de la reconstrucción de dinero.

El riesgo real de este módulo no es que reviente, es que devuelva cifras plausibles
pero equivocadas. Por eso los tests fijan las reglas de signo y los casos límite.
"""

from dataclasses import dataclass

from fantasy.analytics.money import (
    SALDO_INCORPORACION_TARDIA,
    SALDO_INICIAL_POR_DEFECTO,
    clasificar,
    construir_balances,
    detectar_flujos_desconocidos,
    saldo_inicial_minimo,
)


@dataclass
class Mov:
    """Movimiento mínimo, con la forma real que devuelve la API."""

    movement_id: str
    movement_type: int
    movement_date: str
    amount: int | None = None
    user1_id: str | None = None
    user2_id: str | None = None
    player_id: str | None = None
    week_number: int | None = None


def test_venta_al_mercado_suma_y_compra_resta():
    venta = Mov("1", 31, "2026-08-13T10:00", amount=1000, user1_id="A")
    compra = Mov("2", 33, "2026-08-13T11:00", amount=400, user1_id="A")

    assert clasificar(venta) == [("A", 1000, "Venta al mercado", "venta_mercado")]
    assert clasificar(compra)[0][1] == -400


def test_traspaso_genera_dos_apuntes_opuestos():
    """El dinero no se crea: lo que sale de uno entra en el otro."""
    mov = Mov("3", 1, "2026-08-14T10:00", amount=5000, user1_id="PAGA", user2_id="COBRA")
    apuntes = clasificar(mov)

    assert len(apuntes) == 2
    assert sum(importe for _, importe, _, _ in apuntes) == 0
    por_manager = {m: imp for m, imp, _, _ in apuntes}
    assert por_manager["PAGA"] == -5000
    assert por_manager["COBRA"] == 5000


def test_premio_de_jornada_suma_e_indica_la_jornada():
    mov = Mov("4", 6, "2026-08-20T10:00", amount=1_300_000, user1_id="A", week_number=2)
    manager, importe, concepto, origen = clasificar(mov)[0]

    assert (manager, importe, origen) == ("A", 1_300_000, "premio_jornada")
    assert "jornada 2" in concepto


def test_eventos_sin_importe_no_generan_apuntes():
    """Altas y alineaciones no mueven dinero."""
    assert clasificar(Mov("5", 9, "2026-08-12T10:00", user1_id="A")) == []
    assert clasificar(Mov("6", 31, "2026-08-12T10:00", amount=None, user1_id="A")) == []


def test_caja_estimada_es_saldo_inicial_mas_flujo():
    movs = [
        Mov("1", 31, "2026-08-13T10:00", amount=10_000_000, user1_id="A"),
        Mov("2", 33, "2026-08-14T10:00", amount=3_000_000, user1_id="A"),
    ]
    bal = construir_balances(movs)["A"]

    assert bal.flujo_neto == 7_000_000
    assert bal.caja_estimada == SALDO_INICIAL_POR_DEFECTO + 7_000_000
    assert bal.num_movimientos == 2


def test_las_diferencias_entre_managers_no_dependen_del_saldo_inicial():
    """Lo exacto del sistema: cambiar S desplaza todas las cajas por igual."""
    movs = [
        Mov("1", 31, "2026-08-13T10:00", amount=8_000_000, user1_id="A"),
        Mov("2", 33, "2026-08-13T11:00", amount=5_000_000, user1_id="B"),
    ]
    bajo = construir_balances(movs, saldo_inicial=50_000_000)
    alto = construir_balances(movs, saldo_inicial=900_000_000)

    dif_bajo = bajo["A"].caja_estimada - bajo["B"].caja_estimada
    dif_alto = alto["A"].caja_estimada - alto["B"].caja_estimada
    assert dif_bajo == dif_alto == 13_000_000


def test_manager_sin_movimientos_se_trata_como_incorporacion_tardia():
    """Aplicarle el saldo fundacional le inflaría la caja."""
    movs = [Mov("1", 31, "2026-08-13T10:00", amount=1_000, user1_id="A")]
    balances = construir_balances(movs, managers_conocidos=["A", "NUEVO"])

    nuevo = balances["NUEVO"]
    assert nuevo.incorporacion_tardia
    assert nuevo.caja_estimada == SALDO_INCORPORACION_TARDIA
    assert not balances["A"].incorporacion_tardia


def test_saldo_inicial_minimo_cubre_el_peor_descubierto():
    """S debe bastar para que nadie quede en negativo en ningún momento."""
    movs = [
        Mov("1", 33, "2026-08-13T10:00", amount=30_000_000, user1_id="A"),
        Mov("2", 33, "2026-08-14T10:00", amount=20_000_000, user1_id="A"),
        Mov("3", 31, "2026-08-15T10:00", amount=45_000_000, user1_id="A"),
    ]
    # Gasta 50 antes de recuperar 45: en el peor momento debe 50.
    assert saldo_inicial_minimo(movs) == 50_000_000


def test_detecta_tipos_con_dinero_no_contemplados():
    """La alarma: un tipo nuevo con importe desviaría todos los saldos en silencio."""
    movs = [
        Mov("1", 31, "2026-08-13T10:00", amount=1_000, user1_id="A"),
        Mov("2", 77, "2026-08-14T10:00", amount=9_999, user1_id="A"),
        Mov("3", 9, "2026-08-14T10:00", user1_id="A"),
    ]
    assert detectar_flujos_desconocidos(movs) == {77: 1}


def test_movimientos_sin_fecha_se_descartan():
    """Sin fecha no hay orden, y sin orden el peor descubierto no significa nada."""
    movs = [Mov("1", 31, None, amount=1_000, user1_id="A")]
    assert construir_balances(movs) == {}
