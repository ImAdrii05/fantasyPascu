"""Sistema de diseño del panel: tokens, iconos y componentes densos de tabla.

Separado de `app.py` a propósito: `app.py` decide QUÉ se muestra y este módulo
decide CÓMO se ve. Así el día que cambie una consulta no se toca el diseño, y al
revés.

Los componentes devuelven cadenas HTML en vez de pintar directamente para poder
componer una tabla entera y mandarla a Streamlit de una sola vez: `st.dataframe`
no admite fotos, chips ni números coloreados, que es justo lo que hace legible
una tabla de mercado con 800 jugadores.
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

# =============================================================================
# CONTRATO DE DISEÑO
# =============================================================================
# Se emite como comentario HTML dentro del propio marcado para que la decisión
# viaje con el artefacto y se pueda auditar sobre el render, no solo en el repo.
DESIGN_CONTRACT = """
<!--
THESIS: aquí el color significa dinero. El cromo es tinta y papel sin matices, y
la saturación queda reservada a lo que cambió de precio y a la demarcación del
jugador. Rechaza el panel oscuro con neones y tarjetas iguales que es el patrón
por defecto de la categoría.
OWN-WORLD: masthead y cabeceras de tabla en tinta #0B0D0E; superficie de datos en
papel blanco con cebra #F7F8F9 y filetes de 1px #E4E7E9; Barlow para texto y
Barlow Condensed en versales para etiquetas; cifras tabulares en todas partes;
chips de demarcación en cinco tonos fijos; barra proporcional dentro de la celda
de variación.
STORY: el usuario recorre cientos de jugadores, ve en un vistazo quién se ha
movido y cuánto, y decide una puja antes de que cierre el mercado.
FIRST VIEWPORT: barra de tinta con el nombre y los hechos del snapshot; debajo el
raíl de pestañas; debajo la tabla densa ocupando el resto de la pantalla con la
cabecera fija al hacer scroll.
FORM: terminal de datos deportivos; la gramática de FútbolFantasy ejecutada con
oficio moderno. Dirección anclada por el brief del usuario, que manda sobre la
tirada (seed 244f669d).
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its
provenance.
-->
"""

# =============================================================================
# TOKENS
# =============================================================================
# El verde y el rojo de FútbolFantasy (#00A04F / #E60000) no llegan a 4.5:1 sobre
# blanco, y aquí son cifras de 14px en negrita, no texto grande. Se oscurecen lo
# justo para pasar el contraste sin perder la lectura de "sube" y "baja".
TOKENS = {
    "ink": "#0B0D0E",
    "ink_2": "#191D21",
    "ink_3": "#2A2F34",
    "paper": "#FFFFFF",
    "paper_2": "#F7F8F9",
    "paper_3": "#EEF0F2",
    "line": "#E4E7E9",
    "line_strong": "#C9CFD4",
    "text": "#15181A",
    "text_2": "#6B7278",
    "up": "#00824A",
    "down": "#D4001A",
    "up_soft": "#E4F3EB",
    "down_soft": "#FCE8EA",
    "focus": "#1F4FD8",
}

# Un tono por demarcación. Es información, no decoración: la demarcación es lo
# primero que se filtra al buscar un fichaje.
POSITION_COLORS = {
    "portero": "#B26A00",
    "defensa": "#1F4FD8",
    "centrocampista": "#00726E",
    "delantero": "#C23400",
    "entrenador": "#4A4F54",
}

POSITION_ABBR = {
    "portero": "POR",
    "defensa": "DEF",
    "centrocampista": "MED",
    "delantero": "DEL",
    "entrenador": "ENT",
}


def position_key(position: str | None) -> str:
    """Normaliza el nombre de demarcación a una de las cinco claves conocidas."""
    if not position:
        return "entrenador"
    p = str(position).strip().lower()
    for key in POSITION_COLORS:
        if p.startswith(key[:4]):
            return key
    return "entrenador"


# =============================================================================
# ICONOS
# =============================================================================
# Dibujados a mano con una sola rejilla (24), un solo grosor (1.75) y remates
# redondos. Nada de emoji: un emoji lo dibuja el sistema operativo, así que
# cambia de forma y de color en cada máquina y nunca pertenece al diseño.
_ICON_PATHS = {
    "trend_up": '<path d="M3 17 9.5 10.5 13.5 14.5 21 7"/><path d="M15 7h6v6"/>',
    "trend_down": '<path d="M3 7 9.5 13.5 13.5 9.5 21 17"/><path d="M15 17h6v-6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h10M18 18h2"/>'
    '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "trophy": '<path d="M7 4h10v5a5 5 0 0 1-10 0V4Z"/><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3"/>'
    '<path d="M12 14v4M8.5 21h7M10 18h4"/>',
    "wallet": '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M16 14h2"/>'
    '<path d="M18 6V4.5a1.5 1.5 0 0 0-1.9-1.4L5 6"/>',
    "chart": '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 20v-6M13 20V8M18 20v-9"/>',
    "shirt": '<path d="M9 3 4 6l2 4 2-1v9h8V9l2 1 2-4-5-3-2 2h-2L9 3Z"/>',
    "pitch": '<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M12 5v14"/>'
    '<circle cx="12" cy="12" r="2.5"/><path d="M3 9h3v6H3M21 9h-3v6h3"/>',
    "alert": '<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4M12 17.2v.1"/>',
    "dot": '<circle cx="12" cy="12" r="4.5"/>',
    "caret_down": '<path d="m7 10 5 5 5-5"/>',
    "caret_up": '<path d="m7 14 5-5 5 5"/>',
}


def icon(name: str, size: int = 16, cls: str = "") -> str:
    """Devuelve un SVG en línea del set propio. `name` desconocido no pinta nada."""
    path = _ICON_PATHS.get(name)
    if not path:
        return ""
    classes = f"ic {cls}".strip()
    return (
        f'<svg class="{classes}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )


# =============================================================================
# COMPONENTES
# =============================================================================


def pos_chip(position: str | None) -> str:
    """Chip de demarcación: tres letras sobre su color."""
    key = position_key(position)
    return f'<span class="chip" style="background:{POSITION_COLORS[key]}">{POSITION_ABBR[key]}</span>'


def player_cell(name: str, team: str | None, position: str | None, img_url: str | None) -> str:
    """Celda de jugador: foto, chip de demarcación, nombre y equipo."""
    img = escape(img_url or "", quote=True)
    photo = f'<img class="pc-img" src="{img}" alt="" loading="lazy">' if img else '<span class="pc-img pc-img-empty"></span>'
    return (
        '<div class="pc">'
        f'<div class="pc-ph">{photo}{pos_chip(position)}</div>'
        '<div class="pc-tx">'
        f'<span class="pc-name">{escape(str(name))}</span>'
        f'<span class="pc-team">{escape(str(team or "Sin equipo"))}</span>'
        "</div></div>"
    )


def delta_cell(text: str, pct: float | None, ratio: float = 0.0) -> str:
    """Celda de variación con barra proporcional dentro de la propia celda.

    Args:
        ratio: Magnitud relativa al mayor movimiento de la tabla, de 0 a 1. Es lo
            que permite comparar de un vistazo sin leer todas las cifras.
    """
    if pct is None:
        return '<span class="muted">—</span>'
    direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
    # Suelo del 18%: una barra proporcional pura deja los movimientos pequeños
    # como una astilla de un píxel, que se lee como un defecto y no como un dato.
    width = 18 + max(0.0, min(1.0, abs(ratio))) * 82
    pct_txt = f"{pct:+.2f}%".replace(".", ",")
    return (
        f'<span class="dl dl-{direction}">'
        f'<span class="dl-bar" style="width:{width:.1f}%"></span>'
        f'<span class="dl-v">{escape(text)}</span>'
        f'<span class="dl-p">{pct_txt}</span>'
        "</span>"
    )


def tag(text: str, kind: str = "neutral") -> str:
    """Etiqueta pequeña. `kind`: neutral | live | warn."""
    return f'<span class="tag tag-{kind}">{escape(text)}</span>'


def bar_cell(pct: float | None, label: str | None = None) -> str:
    """Barra de porcentaje con su cifra, para minutos disputados."""
    if pct is None:
        return '<span class="muted">—</span>'
    value = max(0.0, min(100.0, float(pct)))
    shown = label if label is not None else f"{value:.0f}%"
    return (
        '<span class="pb">'
        f'<span class="pb-t" style="width:{value:.1f}%"></span>'
        f'<span class="pb-l">{escape(shown)}</span>'
        "</span>"
    )


def data_table(
    columns: list[dict[str, Any]],
    rows: Iterable[list[str]],
    max_height: str = "66vh",
    sort: dict[str, str] | None = None,
) -> str:
    """Compone una tabla densa con cabecera fija.

    Args:
        columns: Cada columna es {"label", "align" (left|right|center), "cls"}.
            `cls` admite `hide-sm` para que la columna desaparezca en móvil.
            Con "sort" la cabecera se vuelve pulsable para ordenar por ella.
        rows: Filas ya convertidas a HTML, en el mismo orden que `columns`.
        sort: {"param", "current", "dir", "keep"}. El orden viaja en la URL
            porque pulsar una cabecera recarga la página: así el estado
            sobrevive, y además una vista ordenada se puede guardar o compartir
            como enlace. `keep` son los parámetros ya codificados que hay que
            arrastrar (los filtros) para no perderlos al ordenar.
    """

    def head_cell(c: dict[str, Any]) -> str:
        label = escape(str(c["label"]))
        key = c.get("sort")
        if not (sort and key):
            return f'<th class="al-{c.get("align", "left")} {c.get("cls", "")}">{label}</th>'
        activa = key == sort.get("current")
        descendente = sort.get("dir", "desc") == "desc"
        siguiente = "asc" if (activa and descendente) else "desc"
        flecha = icon("caret_up" if (activa and not descendente) else "caret_down", 13, "th-c")
        keep = sort.get("keep", "")
        href = f'?{keep}{sort["param"]}={key}&dir={siguiente}'
        clase = "th-s th-a" if activa else "th-s"
        # El `href` es la red de seguridad: si el puente de JavaScript no llega a
        # montarse, el enlace ordena igual recargando. Con el puente, `data-sort`
        # se intercepta y se reordena sin recargar nada.
        return (
            f'<th class="al-{c.get("align", "left")} {c.get("cls", "")}">'
            f'<a class="{clase}" href="{href}" data-sort="{key}" '
            f'title="Ordenar por {label}">{label}{flecha}</a></th>'
        )

    head = "".join(head_cell(c) for c in columns)
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="al-{columns[i].get("align", "left")} {columns[i].get("cls", "")}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(
            f'<tr><td class="dt-empty" colspan="{len(columns)}">Ningún jugador cumple estos filtros.</td></tr>'
        )
    return (
        f'<div class="dt-wrap" style="max-height:{max_height}">'
        f'<table class="dt"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def masthead(title: str, facts: list[tuple[str, str, str]]) -> str:
    """Barra de tinta superior: nombre del panel y hechos del snapshot.

    Args:
        facts: Tripletas (icono, etiqueta, valor). Son datos, no métricas de
            escaparate: ocupan una línea, no una tarjeta cada uno.
    """
    items = "".join(
        f'<span class="mh-f">{icon(ic, 14)}'
        f'<span class="mh-fl">{escape(label)}</span>'
        f'<span class="mh-fv">{escape(value)}</span></span>'
        for ic, label, value in facts
    )
    return (
        '<header class="mh">'
        f'<span class="mh-t">{escape(title)}</span>'
        f'<div class="mh-fs">{items}</div>'
        "</header>"
    )


def player_header(name: str, team: str | None, position: str | None, img_url: str | None, extra: str = "") -> str:
    """Barra de identidad de un jugador, para encabezar su ficha."""
    return (
        '<div class="ph">'
        + player_cell(name, team, position, img_url)
        + (f'<div class="ph-x">{extra}</div>' if extra else "")
        + "</div>"
    )


def section(title: str, icon_name: str = "", note: str = "") -> str:
    """Encabezado de sección con filete. Sin kicker: el título se basta."""
    glyph = icon(icon_name, 17, "sc-i") if icon_name else ""
    sub = f'<p class="sc-n">{escape(note)}</p>' if note else ""
    return f'<div class="sc"><h2 class="sc-t">{glyph}{escape(title)}</h2>{sub}</div>'


def notice(text: str, kind: str = "info", icon_name: str = "alert") -> str:
    """Aviso en línea. Se usa sobre todo para marcar un dato como estimado."""
    return (
        f'<div class="nt nt-{kind}">{icon(icon_name, 16, "nt-i")}'
        f'<span>{text}</span></div>'
    )


def stat_row(items: list[tuple[str, str, str, str]]) -> str:
    """Fila de cifras separadas por filetes, no tarjetas apiladas.

    Args:
        items: Cuádruplas (etiqueta, valor, apoyo, tono: ''|'up'|'down'). El
            valor y el apoyo se insertan sin escapar para poder llevar marcado;
            escapa en origen lo que venga de la base de datos.
    """
    cells = "".join(
        f'<div class="sr-i"><span class="sr-l">{escape(label)}</span>'
        f'<span class="sr-v {tone}">{value}</span>'
        + (f'<span class="sr-s {tone}">{sub}</span>' if sub else "")
        + "</div>"
        for label, value, sub, tone in items
    )
    return f'<div class="sr">{cells}</div>'


def podium(entries: list[dict[str, Any]]) -> str:
    """Los tres primeros de la liga, como un listado jerárquico y no como tarjetas.

    Cada entrada: {"pos", "team", "manager", "points", "value"}.
    """
    rows = []
    for e in entries:
        rows.append(
            '<li class="pd-i">'
            f'<span class="pd-p">{escape(str(e["pos"]))}</span>'
            '<span class="pd-tx">'
            f'<span class="pd-t">{escape(str(e["team"]))}</span>'
            f'<span class="pd-m">{escape(str(e["manager"]))}</span>'
            "</span>"
            f'<span class="pd-pt">{escape(str(e["points"]))}<span class="pd-u">pts</span></span>'
            f'<span class="pd-v">{escape(str(e["value"]))}</span>'
            "</li>"
        )
    return f'<ol class="pd">{"".join(rows)}</ol>'


# =============================================================================
# HOJA DE ESTILOS
# =============================================================================
CSS = (
    DESIGN_CONTRACT
    + """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&display=swap');

:root {
  --ink: #0B0D0E;
  --ink-2: #191D21;
  --ink-3: #2A2F34;
  --paper: #FFFFFF;
  --paper-2: #F7F8F9;
  --paper-3: #EEF0F2;
  --line: #E4E7E9;
  --line-strong: #C9CFD4;
  --text: #15181A;
  --text-2: #6B7278;
  --up: #00824A;
  --down: #D4001A;
  --up-soft: #E4F3EB;
  --down-soft: #FCE8EA;
  --focus: #1F4FD8;
  --sp: 8px;
  --r: 6px;
  --mono-num: "Barlow", system-ui, sans-serif;
}

/* ---- Base --------------------------------------------------------------- */
html, body, [class*="st-"], .stApp, button, input, select, textarea {
  font-family: "Barlow", system-ui, -apple-system, sans-serif;
}
/* Streamlit dibuja sus iconos con ligaduras de Material Symbols. La regla de
   arriba es ancha a propósito, pero si también alcanza a esos spans la ligadura
   no se forma y el icono se lee como texto ("keyboard_double_arrow_left"). */
[data-testid="stIconMaterial"],
.material-icons,
.material-symbols-rounded,
.material-symbols-outlined {
  font-family: "Material Symbols Rounded", "Material Icons", sans-serif !important;
}

.stApp { background: var(--paper-2); color: var(--text); }
.block-container { padding: 14px 20px 48px !important; max-width: 1500px; }

/* Las superficies del navegador que no dibujamos también son el diseño. */
::selection { background: var(--ink); color: #fff; }
* { caret-color: var(--focus); }
*:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
  border-radius: 3px;
}
::-webkit-scrollbar { width: 11px; height: 11px; }
::-webkit-scrollbar-track { background: var(--paper-2); }
::-webkit-scrollbar-thumb {
  background: var(--line-strong);
  border: 3px solid var(--paper-2);
  border-radius: 99px;
}
::-webkit-scrollbar-thumb:hover { background: #A6ADB3; }

/* Cromo de Streamlit que no pertenece a este diseño. La cabecera NO se oculta:
   cuando la barra lateral está plegada, el botón para volver a abrirla vive
   dentro de ella, así que esconderla dejaba el menú cerrado para siempre. Se
   deja sin fondo y sin alto, pero visible y pulsable. */
header[data-testid="stHeader"] {
  background: transparent !important;
  height: 0 !important;
  min-height: 0 !important;
  overflow: visible !important;
}
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stStatusWidget"], [data-testid="stDecoration"], #MainMenu, footer {
  display: none !important;
}
/* El toolbar se queda: dentro vive el botón de reabrir el menú. Se deja
   transparente y sin capturar clics salvo el propio botón. */
[data-testid="stToolbar"] { background: transparent !important; pointer-events: none; }
[data-testid="stToolbar"] * { pointer-events: none; }
[data-testid="stExpandSidebarButton"] {
  pointer-events: auto !important;
  position: fixed !important; top: 22px; left: 32px; z-index: 80;
  width: 32px; height: 32px; border-radius: 5px;
  background: rgba(255,255,255,.14) !important;
  color: #FFFFFF !important;
  transition: background-color .14s cubic-bezier(.16,1,.3,1);
}
[data-testid="stExpandSidebarButton"]:hover { background: rgba(255,255,255,.26) !important; }
[data-testid="stExpandSidebarButton"] span { color: #FFFFFF !important; }
/* Con el menú plegado el botón cae sobre el masthead, así que se le hace hueco. */
[data-testid="stSidebar"][aria-expanded="false"] ~ div .mh { padding-left: 76px; }

.ic { flex: none; vertical-align: -0.18em; }

/* ---- Masthead ----------------------------------------------------------- */
.mh {
  display: flex; align-items: center; justify-content: space-between;
  gap: 20px; flex-wrap: wrap;
  background: var(--ink); color: #fff;
  padding: 13px 18px; border-radius: var(--r);
  margin-bottom: 14px;
}
.mh-t {
  font-family: "Barlow Condensed", sans-serif;
  font-size: 25px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; line-height: 1;
}
.mh-fs { display: flex; gap: 22px; flex-wrap: wrap; align-items: center; }
.mh-f { display: inline-flex; align-items: center; gap: 7px; color: rgba(255,255,255,.62); }
.mh-fl {
  font-family: "Barlow Condensed", sans-serif;
  font-size: 12.5px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
}
.mh-fv {
  color: #fff; font-size: 14px; font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ---- Secciones ---------------------------------------------------------- */
.sc { margin: 26px 0 12px; padding-bottom: 9px; border-bottom: 1px solid var(--line); }
.sc:first-child { margin-top: 6px; }
.sc-t {
  display: flex; align-items: center; gap: 9px; margin: 0;
  font-size: 17px; font-weight: 700; letter-spacing: -0.01em; color: var(--text);
}
.sc-i { color: var(--text-2); }
.sc-n { margin: 5px 0 0; font-size: 13.5px; color: var(--text-2); max-width: 74ch; line-height: 1.5; }

/* ---- Fila de cifras ----------------------------------------------------- */
.sr {
  display: flex; flex-wrap: wrap;
  background: var(--paper); border: 1px solid var(--line); border-radius: var(--r);
  overflow: hidden;
}
.sr-i {
  flex: 1 1 150px; min-width: 0;
  padding: 11px 15px; border-right: 1px solid var(--line);
  display: flex; flex-direction: column; gap: 3px;
}
.sr-i:last-child { border-right: 0; }
.sr-l {
  font-family: "Barlow Condensed", sans-serif;
  font-size: 12px; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--text-2);
}
.sr-v {
  font-size: 19px; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums; letter-spacing: -0.015em;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sr-v.up { color: var(--up); }
.sr-v.down { color: var(--down); }
.sr-s {
  font-size: 13px; font-weight: 600; color: var(--text-2);
  font-variant-numeric: tabular-nums;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sr-s.up { color: var(--up); }
.sr-s.down { color: var(--down); }

/* ---- Tabla densa -------------------------------------------------------- */
.dt-wrap {
  overflow: auto; background: var(--paper);
  border: 1px solid var(--line); border-radius: var(--r);
}
.dt { width: 100%; border-collapse: separate; border-spacing: 0; }
.dt thead th {
  position: sticky; top: 0; z-index: 2;
  background: var(--ink); color: #fff;
  font-family: "Barlow Condensed", sans-serif;
  font-size: 12.5px; font-weight: 600; letter-spacing: 0.09em; text-transform: uppercase;
  padding: 10px 12px; white-space: nowrap;
}
/* Cabecera pulsable. El acento queda abajo y no como color de texto, para que
   la fila de cabecera siga leyéndose como un bloque de tinta continuo. */
.dt thead th:has(.th-s) { padding: 0; }
.th-s {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 10px 12px; color: rgba(255,255,255,.72);
  text-decoration: none; cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color .14s cubic-bezier(.16,1,.3,1), border-color .14s cubic-bezier(.16,1,.3,1);
}
.al-right .th-s { flex-direction: row-reverse; }
.th-s:hover { color: #fff; border-bottom-color: rgba(255,255,255,.35); }
.th-s:focus-visible { outline-offset: -3px; }
.th-a { color: #fff; border-bottom-color: #fff; }
.th-c { opacity: 0; transition: opacity .14s ease; }
.th-s:hover .th-c { opacity: .6; }
.th-a .th-c { opacity: 1; }

.dt tbody td {
  padding: 7px 12px; font-size: 14px; color: var(--text);
  border-bottom: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.dt tbody tr:nth-child(even) td { background: var(--paper-2); }
.dt tbody tr:hover td { background: var(--paper-3); }
.dt tbody tr:last-child td { border-bottom: 0; }
.al-left { text-align: left; }
.al-right { text-align: right; }
.al-center { text-align: center; }
.dt-empty { text-align: center; color: var(--text-2); padding: 34px 12px !important; }
.dt .rk { color: var(--text-2); font-weight: 600; width: 42px; }
.dt .num { font-weight: 600; white-space: nowrap; }
.muted { color: var(--text-2); }

/* ---- Celda de jugador --------------------------------------------------- */
.pc { display: flex; align-items: center; gap: 10px; min-width: 0; }
.pc-ph { position: relative; flex: none; }
.pc-img {
  width: 34px; height: 34px; border-radius: 50%;
  object-fit: cover; background: var(--paper-3); display: block;
}
.pc-img-empty { display: block; }
.chip {
  position: absolute; left: -3px; bottom: -3px;
  color: #fff; font-family: "Barlow Condensed", sans-serif;
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.05em;
  padding: 1px 4px; border-radius: 3px;
  border: 1.5px solid var(--paper);
}
.pc-tx { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.pc-name {
  font-size: 14.5px; font-weight: 600; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pc-team { font-size: 12.5px; color: var(--text-2); }

/* ---- Variación con barra en celda --------------------------------------- */
.dl {
  position: relative; display: inline-flex; align-items: baseline;
  justify-content: flex-end; gap: 8px;
  padding: 3px 7px; border-radius: 4px; min-width: 128px;
  overflow: hidden;
}
.dl-bar {
  position: absolute; right: 0; top: 0; bottom: 0;
  border-radius: 4px; opacity: 1;
}
.dl-up .dl-bar { background: var(--up-soft); }
.dl-down .dl-bar { background: var(--down-soft); }
.dl-flat .dl-bar { background: var(--paper-3); }
.dl-v, .dl-p { position: relative; font-variant-numeric: tabular-nums; }
.dl-v { font-size: 14px; font-weight: 700; }
.dl-p { font-size: 12.5px; font-weight: 600; opacity: .82; }
.dl-up .dl-v, .dl-up .dl-p { color: var(--up); }
.dl-down .dl-v, .dl-down .dl-p { color: var(--down); }
.dl-flat .dl-v, .dl-flat .dl-p { color: var(--text-2); }

/* ---- Barra de porcentaje ------------------------------------------------ */
.pb {
  position: relative; display: inline-block; min-width: 108px;
  background: var(--paper-3); border-radius: 3px; overflow: hidden;
  padding: 3px 8px; text-align: right;
}
.pb-t { position: absolute; left: 0; top: 0; bottom: 0; background: var(--ink-3); opacity: .16; }
.pb-l { position: relative; font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }

/* ---- Importes y movimientos --------------------------------------------- */
.mn { font-weight: 700; font-variant-numeric: tabular-nums; }
.mn-up { color: var(--up); }
.mn-down { color: var(--down); }
.mn-flat { color: var(--text-2); }
.mv { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.mv-i { color: var(--text-2); }
.lg-n {
  margin: 0 0 12px;
  font-family: "Barlow Condensed", sans-serif;
  font-size: 15px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-2);
}

/* ---- Etiquetas ---------------------------------------------------------- */
.tag {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: "Barlow Condensed", sans-serif;
  font-size: 11.5px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 3px;
  border: 1px solid var(--line-strong); color: var(--text-2);
}
.tag-live { background: var(--up); border-color: var(--up); color: #fff; }
.tag-warn { background: var(--down-soft); border-color: var(--down); color: var(--down); }

/* ---- Avisos ------------------------------------------------------------- */
.nt {
  display: flex; align-items: flex-start; gap: 9px;
  background: var(--paper); border: 1px solid var(--line);
  border-radius: var(--r); padding: 11px 14px;
  font-size: 13.5px; line-height: 1.55; color: var(--text-2);
}
.nt b, .nt strong { color: var(--text); font-weight: 600; }
.nt-i { color: var(--text-2); margin-top: 2px; }
.nt-warn { background: var(--down-soft); border-color: #F3C9CE; color: #7A1018; }
.nt-warn .nt-i { color: var(--down); }

/* ---- Ficha de jugador --------------------------------------------------- */
.ph {
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  background: var(--ink); color: #fff;
  border-radius: var(--r); padding: 12px 16px; margin-bottom: 10px;
}
.ph .pc-img { width: 44px; height: 44px; }
.ph .pc-name { font-size: 18px; font-weight: 700; color: #fff; }
.ph .pc-team { font-size: 13px; color: rgba(255,255,255,.64); }
.ph .chip { border-color: var(--ink); }
.ph-x { display: flex; align-items: center; gap: 8px; }

/* ---- Podio -------------------------------------------------------------- */
.pd { list-style: none; margin: 0; padding: 0;
  background: var(--paper); border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
.pd-i {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 16px; border-bottom: 1px solid var(--line);
}
.pd-i:last-child { border-bottom: 0; }
.pd-i:first-child { background: var(--ink); color: #fff; }
.pd-i:first-child .pd-m { color: rgba(255,255,255,.66); }
.pd-i:first-child .pd-v { color: rgba(255,255,255,.78); }
.pd-i:first-child .pd-p { color: #fff; border-color: rgba(255,255,255,.4); }
.pd-p {
  flex: none; width: 26px; height: 26px; border-radius: 50%;
  border: 1.5px solid var(--line-strong); color: var(--text-2);
  display: grid; place-items: center;
  font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums;
}
.pd-tx { display: flex; flex-direction: column; flex: 1; min-width: 0; line-height: 1.3; }
.pd-t { font-size: 15.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pd-m { font-size: 12.5px; color: var(--text-2); }
.pd-pt { font-size: 19px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.pd-u { font-size: 11.5px; font-weight: 600; opacity: .55; margin-left: 3px; }
.pd-v { font-size: 13.5px; color: var(--text-2); font-variant-numeric: tabular-nums; min-width: 72px; text-align: right; }

/* ---- Controles de Streamlit --------------------------------------------- */
[data-testid="stSidebar"] { background: var(--paper); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] .block-container { padding-top: 18px !important; }

[data-baseweb="tab-list"] {
  gap: 2px !important; background: var(--ink); padding: 4px !important;
  border-radius: var(--r); margin-bottom: 16px;
}
[data-baseweb="tab-list"] button[data-baseweb="tab"] {
  background: transparent !important; color: rgba(255,255,255,.62) !important;
  border-radius: 4px !important; padding: 7px 15px !important; height: auto !important;
  font-family: "Barlow Condensed", sans-serif !important;
  font-size: 14.5px !important; font-weight: 600 !important;
  letter-spacing: 0.07em; text-transform: uppercase;
  transition: color .16s cubic-bezier(.16,1,.3,1), background-color .16s cubic-bezier(.16,1,.3,1);
}
[data-baseweb="tab-list"] button[data-baseweb="tab"]:hover { color: #fff !important; }
[data-baseweb="tab-list"] button[aria-selected="true"] {
  background: var(--paper) !important; color: var(--ink) !important;
}
[data-baseweb="tab-list"] [data-baseweb="tab-highlight"],
[data-baseweb="tab-list"] [data-baseweb="tab-border"] { display: none !important; }

/* Botones que el puente de ordenación pulsa por nosotros: nunca se ven. */
.st-key-ordenadores { display: none !important; }

/* El iframe del puente solo lleva un script y no pinta nada. No se oculta con
   display:none, que en algunos navegadores impide que el iframe llegue a
   cargar: se deja sin alto y fuera del flujo. */
[data-testid="stCustomComponentV1"] {
  height: 0 !important; min-height: 0 !important; border: 0 !important;
  position: absolute; visibility: hidden;
}

.stSlider [data-baseweb="slider"] div[role="slider"] { border-color: var(--ink) !important; }
[data-testid="stWidgetLabel"] p {
  font-family: "Barlow Condensed", sans-serif;
  font-size: 12.5px; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--text-2);
}
[data-testid="stSidebar"] hr { border-color: var(--line); margin: 14px 0; }

/* ---- Adaptación ---------------------------------------------------------
   El corte está en 1120px y no en el ancho de móvil a propósito: con la barra
   lateral abierta, una ventana de escritorio deja al contenido bastante menos
   espacio del que aparenta, y la tabla se cortaba por la derecha. */
@media (max-width: 1120px) {
  .hide-sm { display: none !important; }
  .dl { min-width: 104px; }
}

@media (max-width: 760px) {
  .block-container { padding: 10px 14px 40px !important; }
  .mh { padding: 11px 14px; gap: 10px; }
  .mh-t { font-size: 21px; }
  .mh-fs { gap: 14px; }
  .dt tbody td { padding: 6px 9px; font-size: 13.5px; }
  .dt thead th { padding: 9px 9px; font-size: 11.5px; }
  .pc-img { width: 30px; height: 30px; }
  .dl { min-width: 0; gap: 5px; }
  .dl-p { display: none; }
  .sr-i { flex-basis: 50%; }
  .pd-v { display: none; }
}
</style>
"""
)
