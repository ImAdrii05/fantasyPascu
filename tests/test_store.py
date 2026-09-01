"""Tests de la capa de persistencia. Foco: la paginación de PostgREST.

PostgREST devuelve como mucho 1000 filas y NO señala que ha truncado. Es un fallo
silencioso: los datos simplemente llegan incompletos. `fetch_all` existe para eso,
y merece test propio porque su ausencia no rompe nada de forma visible.
"""

from fantasy.store.supabase import fetch_all


class FakeQuery:
    """Imita el encadenado `.range(...).execute()` de PostgREST."""

    def __init__(self, rows):
        self.rows = rows
        self._start = 0
        self._end = 0

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        class Res:
            pass

        res = Res()
        res.data = self.rows[self._start : self._end + 1]
        return res


def test_fetch_all_recorre_todas_las_paginas():
    rows = [{"id": i} for i in range(2500)]
    out = fetch_all(lambda: FakeQuery(rows), page_size=1000)
    assert len(out) == 2500
    assert out[0]["id"] == 0
    assert out[-1]["id"] == 2499


def test_fetch_all_para_cuando_la_pagina_no_esta_llena():
    """Una página incompleta significa fin de datos: no debe pedir otra."""
    rows = [{"id": i} for i in range(150)]
    out = fetch_all(lambda: FakeQuery(rows), page_size=1000)
    assert len(out) == 150


def test_fetch_all_con_tabla_vacia():
    assert fetch_all(lambda: FakeQuery([]), page_size=1000) == []


def test_fetch_all_multiplo_exacto_del_tamano_de_pagina():
    """Caso límite: con 2000 filas y páginas de 1000, la tercera llega vacía y corta."""
    rows = [{"id": i} for i in range(2000)]
    out = fetch_all(lambda: FakeQuery(rows), page_size=1000)
    assert len(out) == 2000
