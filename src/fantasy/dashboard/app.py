"""Panel de análisis de mercado de LaLiga Fantasy.

Este módulo decide QUÉ se muestra; el sistema de diseño vive en `ui.py` y decide
CÓMO se ve. Las tablas se componen como HTML propio en vez de `st.dataframe`
porque ésta no admite fotos, chips de demarcación ni cifras coloreadas, que es
justo lo que hace legible un listado de 800 jugadores.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from html import escape
import hmac
import json
from urllib.parse import urlencode
import textwrap
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from supabase import create_client

from fantasy import config
from fantasy.store.supabase import fetch_all
from fantasy.analytics.clauses import (
    CRITERIOS,
    MIN_PCT_MINUTOS,
    TODOS_CRITERIOS,
    VENTANA_FORMA,
    enriquecer_clausulas,
    proximas_a_abrirse,
    ranking_clausulas,
)
from fantasy.dashboard import ui

# Configuración de página
st.set_page_config(
    page_title="LaLiga Fantasy",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="auto",
)


def render_html(html_str: str) -> None:
    """Renderiza HTML nativo sin que Markdown lo confunda con bloques de código indentados."""
    st.html(textwrap.dedent(html_str).strip())



NO_PLAYER_IMG = "https://assets-fantasy.llt-services.com/players/no-player/no-player-sq_256.png"

# Celda sin dato. Un guion gris, nunca un cero: no es lo mismo "no jugó" que "jugó 0".
MUTED_DASH = '<span class="muted">—</span>'

# El cron escribe una vez al día, así que media hora de caché no deja ver
# nada viejo y ahorra releer la base en cada clic.
CACHE_TTL = 1800


@st.cache_resource
def get_supabase_client():
    """Inicializa la conexión con Supabase con caché para evitar reconexiones."""
    config.validate_supabase_config()
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _df(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """DataFrame a partir de filas, con columnas garantizadas aunque venga vacío."""
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


@st.cache_data(ttl=CACHE_TTL)
def load_market_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Carga jugadores, snapshots diarios y equipos desde Supabase paginando."""
    client = get_supabase_client()

    teams = fetch_all(lambda: client.table("teams").select("id, name, short_name, badge_url"))
    df_teams = _df(teams, ["id", "name", "short_name", "badge_url"])

    players = fetch_all(
        lambda: client.table("players").select(
            "id, name, nickname, position, position_id, team_id, status, image_url"
        )
    )
    df_players = _df(players, ["id", "name", "nickname", "position", "position_id", "team_id", "status", "image_url"])

    return df_players, df_teams


@st.cache_data(ttl=CACHE_TTL)
def load_snapshot_dates() -> list[str]:
    """Fechas con snapshot, de la más antigua a la más reciente.

    Sale de `raw_snapshots`, que guarda una fila por día y endpoint: 57 filas en
    vez de las 48.000 de `player_daily`. Leer el histórico entero solo para
    contar los días costaba casi siete segundos.
    """
    client = get_supabase_client()
    rows = (
        client.table("raw_snapshots")
        .select("snapshot_date")
        .eq("endpoint", "all_players")
        .order("snapshot_date")
        .execute()
        .data
        or []
    )
    return sorted({r["snapshot_date"] for r in rows if r.get("snapshot_date")})


@st.cache_data(ttl=CACHE_TTL)
def load_recent_daily(fechas: tuple[str, ...]) -> pd.DataFrame:
    """Snapshots de los días indicados, normalmente hoy y ayer.

    El mercado solo compara el último día con el anterior. El resto del
    histórico se pide por jugador cuando de verdad hace falta, en su ficha.
    """
    if not fechas:
        return _df([], ["snapshot_date", "player_id", "market_value", "points", "average_points", "played_matches", "minutes_played"])
    client = get_supabase_client()
    daily = fetch_all(
        lambda: client.table("player_daily")
        .select("snapshot_date, player_id, market_value, points, average_points, played_matches, minutes_played")
        .in_("snapshot_date", list(fechas))
        .order("snapshot_date")
        .order("player_id")
    )
    return _df(
        daily,
        ["snapshot_date", "player_id", "market_value", "points", "average_points", "played_matches", "minutes_played"],
    )


@st.cache_data(ttl=CACHE_TTL)
def load_player_history(player_id: str) -> pd.DataFrame:
    """Cotización completa de un jugador, para su ficha. Son 57 filas, no 48.000."""
    client = get_supabase_client()
    rows = fetch_all(
        lambda: client.table("player_daily")
        .select("snapshot_date, player_id, market_value, points")
        .eq("player_id", str(player_id))
        .order("snapshot_date")
    )
    return _df(rows, ["snapshot_date", "player_id", "market_value", "points"])


# TTL corto y a proposito. Una clausula se juega al segundo: media hora de
# cache aqui significaria perder el momento de apertura, que es justo el dato.
@st.cache_data(ttl=90)
def load_squads(league_id: str) -> tuple[pd.DataFrame, str]:
    """Plantillas de todos los managers de la liga, con clausulas en vivo.

    Esto NO sale de Supabase: el cron guarda una foto al dia y una clausula
    cambia de estado a una hora exacta. Se pide a la API en el momento.

    Returns:
        (DataFrame de jugadores, hora de la consulta en formato HH:MM:SS).
    """
    from fantasy.api.client import FantasyApiClient

    client = FantasyApiClient(throttle_seconds=0.3)
    standings, _ = client.get_league_standing(league_id)

    filas = []
    for fila in standings:
        jugadores, _ = client.get_league_team(league_id, fila.league_team_id)
        for j in jugadores:
            d = j.to_dict()
            d["manager_name"] = j.manager_name or fila.manager_name or fila.team_name
            d["clause_open"] = j.clause_open()
            filas.append(d)

    columnas = [
        "league_id", "league_team_id", "manager_id", "manager_name", "player_id",
        "player_name", "position", "position_id", "club_name", "image_url",
        "market_value", "points", "average_points", "buyout_clause",
        "clause_locked_until", "is_shielded", "player_team_id", "clause_open",
    ]
    return _df(filas, columnas), datetime.now().strftime("%H:%M:%S")


@st.cache_data(ttl=CACHE_TTL)
def load_my_teams() -> dict[str, str]:
    """Tu equipo en cada liga ({league_id: team_id}), de la tabla `leagues`.

    Sirve para no ofrecerte como clausulables a tus propios jugadores. Sin la
    migración 004 no hay tabla y se devuelve vacío: entonces no se excluye nada.
    """
    try:
        rows = get_supabase_client().table("leagues").select("id, team_id").execute().data or []
    except Exception:
        return {}
    return {str(r["id"]): str(r["team_id"]) for r in rows if r.get("id") and r.get("team_id")}


def saldo_en_vivo(client, league_id: str) -> int | None:
    """Tu saldo en la liga (`team.money` del endpoint de ligas del usuario).

    Sin caché a propósito: se usa justo antes de pagar, y un saldo de hace unos
    segundos puede no ser el de ahora.
    """
    ligas, _ = client.get_user_leagues()
    return next((lg.team_money for lg in ligas if lg.id == str(league_id)), None)


def mensaje_api(error) -> str:
    """El texto que da LaLiga en un error (`message` del JSON), o el cuerpo a secas."""
    cuerpo = (getattr(error, "response_body", None) or "").strip()
    try:
        datos = json.loads(cuerpo)
        if isinstance(datos, dict) and (datos.get("message") or datos.get("error")):
            return str(datos.get("message") or datos.get("error"))
    except ValueError:
        pass
    return cuerpo[:200] or str(error)


@st.dialog("Pagar cláusula")
def dialogo_clausulazo(league_id: str, fila: dict) -> None:
    """Confirma y paga una cláusula. Antes vuelve a leerla en vivo.

    La lista de la pestaña puede tener hasta 90 s: en ese tiempo el dueño ha podido
    subir la cláusula, blindar al jugador o venderlo. Por eso se relee su plantilla
    justo antes, y se paga la cifra vigente, que es la única que admite la API.
    """
    from fantasy.api.client import FantasyApiClient, FantasyApiError

    nombre = fila.get("player_name") or "el jugador"
    dueno = fila.get("manager_name") or "su mánager"
    client = FantasyApiClient(throttle_seconds=0)

    with st.spinner("Comprobando la cláusula en vivo..."):
        try:
            plantilla, _ = client.get_league_team(league_id, fila["league_team_id"])
        except Exception as e:
            st.error(f"No se pudo comprobar la cláusula: {e}")
            return
    actual = next((j for j in plantilla if j.player_team_id == fila.get("player_team_id")), None)
    if actual is None:
        st.error(f"{nombre} ya no está en el equipo de {dueno}.")
        return
    if not actual.clause_open():
        st.error(f"La cláusula de {nombre} ya no está abierta: la han blindado o vuelve a estar bloqueada.")
        return
    importe = actual.buyout_clause
    if not importe:
        st.error("LaLiga no da el importe de esta cláusula: no se puede pagar desde aquí.")
        return

    anterior = fila.get("buyout_clause")
    if anterior and pd.notnull(anterior) and int(anterior) != importe:
        st.warning(f"La cláusula ha cambiado: antes {format_money(anterior)}, ahora {format_money(importe)}.")

    try:
        saldo = saldo_en_vivo(client, str(league_id))
    except Exception:
        saldo = None

    render_html(
        ui.player_cell(nombre, fila.get("club_name"), fila.get("position"), fila.get("image_url") or NO_PLAYER_IMG)
    )
    hechos = [("Dueño", dueno), ("Cláusula", format_money(importe))]
    if saldo is not None:
        hechos += [("Tu saldo", format_money(saldo)), ("Te quedarían", format_money(saldo - importe))]
    render_html(ui.fact_list(hechos))

    if saldo is not None and saldo < importe:
        st.error(f"No te llega: te faltan {format_money(importe - saldo)}.")
        return

    st.caption("El pago es inmediato y no se puede deshacer.")
    if not st.button(f"Pagar {format_money(importe)}", type="primary", use_container_width=True):
        return

    try:
        client.pay_buyout_clause(league_id, actual.player_team_id, importe)
    except FantasyApiError as e:
        if e.status_code is None:
            # Sin respuesta no se sabe si el pago llegó: reintentar a ciegas podría
            # repetirlo. Se manda a comprobar primero.
            st.error(
                "LaLiga no respondió, así que no se sabe si el pago se ha hecho. Vuelve a "
                "consultar las cláusulas antes de intentarlo otra vez."
            )
        elif e.status_code == 409:
            st.error(
                f"LaLiga dice que la cláusula de {nombre} no está disponible ahora mismo "
                f"(¿la ha pagado otro o la han blindado?). {mensaje_api(e)}"
            )
        else:
            st.error(f"LaLiga rechazó el pago (HTTP {e.status_code}): {mensaje_api(e)}")
        return
    except Exception as e:
        st.error(f"No se pudo pagar la cláusula: {e}")
        return

    load_squads.clear()
    st.session_state["clausulazo_hecho"] = f"¡Fichado! {nombre} es tuyo por {format_money(importe)}."
    st.rerun()


def formatear_cuenta_atras(cuando, ahora=None) -> str:
    """Convierte la hora de apertura de una clausula en una espera legible."""
    if cuando is None or pd.isna(cuando):
        return ui.tag("Abierta", "live")
    ahora = ahora or datetime.now(timezone.utc)
    restante = cuando - ahora
    segundos = restante.total_seconds()
    if segundos <= 0:
        return ui.tag("Abierta", "live")
    dias, resto = divmod(int(segundos), 86400)
    horas, resto = divmod(resto, 3600)
    minutos = resto // 60
    if dias:
        return f'<span class="muted">{dias}d {horas}h</span>'
    if horas:
        return f'<span class="muted">{horas}h {minutos}m</span>'
    # Menos de una hora: es el momento de estar mirando, asi que se destaca.
    return ui.tag(f"{minutos}m", "warn")


# Las cláusulas se abren a una hora exacta y el usuario juega desde España: la hora
# se enseña en la suya. Sin base de zonas (Windows sin `tzdata`) se cae a UTC.
try:
    HORA_ESPANA = ZoneInfo("Europe/Madrid")
except ZoneInfoNotFoundError:
    HORA_ESPANA = timezone.utc
DIAS_SEMANA = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def hora_apertura(cuando, ahora=None) -> str:
    """Hora de apertura legible en horario de España: "hoy 19:28", "mañana 07:10", "jue 30 19:28"."""
    local = cuando.astimezone(HORA_ESPANA)
    hoy = (ahora or datetime.now(timezone.utc)).astimezone(HORA_ESPANA).date()
    if local.date() == hoy:
        dia = "hoy"
    elif local.date() == hoy + timedelta(days=1):
        dia = "mañana"
    else:
        dia = f"{DIAS_SEMANA[local.weekday()]} {local.day}"
    return f"{dia} {local:%H:%M}"


def celda_apertura(cuando, ahora) -> str:
    """Cuenta atrás y, debajo, la hora exacta: un clausulazo se juega a esa hora."""
    cuenta = formatear_cuenta_atras(cuando, ahora)
    if cuando is None or pd.isna(cuando) or cuando <= ahora:
        return cuenta
    return f'<span class="ap">{cuenta}<br><span class="ap-h">{hora_apertura(cuando, ahora)}</span></span>'


@st.cache_data(ttl=CACHE_TTL)
def load_league_market() -> pd.DataFrame:
    """Carga los jugadores actualmente listados en el mercado de la liga privada."""
    client = get_supabase_client()
    rows = fetch_all(
        lambda: client.table("league_market")
        .select("snapshot_date, league_id, market_id, player_id, price, owner_team_id, expires_at")
        .order("snapshot_date", desc=True)
    )
    return _df(rows, ["snapshot_date", "league_id", "market_id", "player_id", "price", "owner_team_id", "expires_at"])


@st.cache_data(ttl=CACHE_TTL)
def load_gameweek_stats() -> pd.DataFrame:
    """Carga las estadísticas por jornada."""
    client = get_supabase_client()
    rows = fetch_all(
        lambda: client.table("player_gameweek_stats")
        .select("player_id, gameweek, points, minutes, goals, assists, yellow_cards, red_cards, saves, goals_conceded")
        .order("player_id")
        .order("gameweek")
    )
    return _df(rows, ["player_id", "gameweek", "points", "minutes", "goals", "assists", "yellow_cards", "red_cards", "saves", "goals_conceded"])


@st.cache_data(ttl=CACHE_TTL)
def load_league_data(df_players: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Carga la clasificación, los movimientos enriquecidos y los nombres de las ligas."""
    client = get_supabase_client()

    standings = fetch_all(
        lambda: client.table("league_standings").select("*").order("snapshot_date", desc=True).order("position")
    )
    df_standings = pd.DataFrame(standings) if standings else pd.DataFrame()

    # Obtener el mapeo exacto de manager_id desde raw_snapshots si existe
    team_to_mgr: dict[str, str] = {}
    mgr_to_name: dict[str, str] = {}
    try:
        res_st_raw = (
            client.table("raw_snapshots")
            .select("payload")
            .like("endpoint", "%standing%")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if res_st_raw.data and res_st_raw.data[0].get("payload"):
            for item in res_st_raw.data[0]["payload"]:
                team = item.get("team") or {}
                mgr = team.get("manager") or {}
                tid = str(team.get("id") or "")
                mid = str(team.get("managerId") or mgr.get("id") or tid)
                mname = mgr.get("managerName") or item.get("manager") or "Mánager"
                if tid:
                    team_to_mgr[tid] = mid
                    mgr_to_name[mid] = mname
    except Exception:
        pass

    if not df_standings.empty and "manager_id" not in df_standings.columns:
        df_standings["manager_id"] = df_standings["league_team_id"].astype(str).map(team_to_mgr)

    # Diccionario de jugadores para nombres en movimientos
    p_dict = {}
    if df_players is not None and not df_players.empty:
        p_dict = dict(zip(df_players["id"].astype(str), df_players["name"]))

    movements = fetch_all(
        lambda: client.table("league_movements").select("*").order("movement_date", desc=True)
    )

    type_descriptions = {
        1: "Compra o clausulazo",
        2: "Venta a un rival",
        31: "Compra en el mercado",
        33: "Venta al mercado",
        6: "Premio de jornada",
        9: "Alineación confirmada",
        10: "Cambio de alineación",
    }

    mov_rows = []
    for r in movements:
        raw = r.get("raw_payload") if isinstance(r.get("raw_payload"), dict) else {}
        pid = str(r.get("player_id") or raw.get("playerMasterId") or raw.get("playerId") or "")
        pname = r.get("player_name") or p_dict.get(pid) or raw.get("playerName")
        amt = r.get("amount") if pd.notnull(r.get("amount")) else raw.get("amount")
        m_type = raw.get("activityTypeId") or r.get("movement_type")
        m_date = r.get("movement_date") or raw.get("createdAt") or raw.get("created")
        u1 = str(r.get("user1_id") or raw.get("user1Id") or "") or None
        u2 = str(r.get("user2_id") or raw.get("user2Id") or "") or None

        try:
            m_type_int = int(m_type) if m_type is not None else 0
        except (ValueError, TypeError):
            m_type_int = 0

        desc = type_descriptions.get(m_type_int, f"Tipo {m_type}")
        date_str = str(m_date).replace("T", " ")[:16] if m_date else "—"

        mov_rows.append({
            "movement_id": r.get("movement_id") or raw.get("id"),
            "league_id": r.get("league_id"),
            "movement_date": m_date,
            "movement_date_str": date_str,
            "activity_type": m_type_int,
            "activity_desc": desc,
            "player_id": pid if pid else None,
            "player_name": pname if pname else ("—" if not amt else f"Jugador {pid}"),
            "amount": int(amt) if amt is not None else None,
            "user1_id": u1,
            "user2_id": u2,
            "manager_name": mgr_to_name.get(u1, "Mánager") if u1 else "—",
            "raw_payload": raw,
        })

    df_movements = pd.DataFrame(mov_rows) if mov_rows else pd.DataFrame()

    league_names: dict[str, str] = {}
    try:
        rows = client.table("leagues").select("id, name").execute().data or []
        league_names = {str(r["id"]): r["name"] for r in rows if r.get("id")}
    except Exception:
        # Sin la migración 004 no hay tabla de ligas: el selector muestra solo IDs.
        pass

    return df_standings, df_movements, league_names


def format_points(val: int | float | None) -> str:
    """Formatea puntos. La API devuelve null para equipos sin puntuar: eso es "sin datos", no un cero."""
    if val is None or pd.isna(val):
        return "—"
    try:
        return f"{float(val):g}"
    except (ValueError, TypeError):
        return str(val)


# Columnas por las que se puede ordenar el mercado, y la columna del DataFrame
# a la que corresponde cada una.
ORDENES_MERCADO = {
    "jugador": "name",
    "valor": "market_value",
    "variacion": "pct_change",
    "puntos": "points",
    "media": "average_points",
}

# Puente entre la cabecera de la tabla y Streamlit. La tabla es HTML, así que un
# clic en ella no puede llamar a Python por sí solo; lo que hace este script es
# traducir ese clic en una pulsación de un botón nativo de Streamlit que está
# oculto. Así se reordena con un rerun normal, sin recargar la página.
#
# Corre dentro de un iframe del mismo origen, que es como Streamlit monta los
# componentes, y por eso alcanza al documento padre.
PUENTE_ORDEN = """
<script>
(function () {
  var doc = window.parent && window.parent.document;
  if (!doc || doc.__puenteOrdenFantasy) return;
  doc.__puenteOrdenFantasy = true;

  function ordenar(ev) {
    var origen = ev.target && ev.target.closest ? ev.target.closest("[data-sort]") : null;
    if (!origen) return;
    if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
    var host = doc.querySelector(".st-key-orden_" + origen.getAttribute("data-sort"));
    var boton = host ? host.querySelector("button") : null;
    if (!boton) return;          // sin botón, el enlace hace su trabajo
    ev.preventDefault();
    boton.click();
  }

  doc.addEventListener("click", ordenar, true);
  doc.addEventListener("keydown", ordenar, true);
})();
</script>
"""


def orden_actual_mercado(has_variation: bool) -> tuple[str, str]:
    """Columna y sentido de ordenación vigentes, con su valor inicial."""
    if "orden" not in st.session_state:
        guardado = st.query_params.get("orden")
        st.session_state.orden = (
            guardado if guardado in ORDENES_MERCADO else ("variacion" if has_variation else "valor")
        )
        sentido = st.query_params.get("dir")
        st.session_state.sentido = sentido if sentido in ("asc", "desc") else "desc"
    if st.session_state.orden == "variacion" and not has_variation:
        st.session_state.orden = "valor"
    return st.session_state.orden, st.session_state.sentido


def pulsar_orden(clave: str) -> None:
    """Aplica el clic en una cabecera: cambia de columna, o invierte el sentido."""
    if st.session_state.orden == clave:
        st.session_state.sentido = "asc" if st.session_state.sentido == "desc" else "desc"
    else:
        st.session_state.orden = clave
        # Los nombres se leen de la A a la Z; todo lo demás, de mayor a menor.
        st.session_state.sentido = "asc" if clave == "jugador" else "desc"
    # La URL se actualiza sin recargar, para que la vista siga siendo compartible.
    st.query_params["orden"] = st.session_state.orden
    st.query_params["dir"] = st.session_state.sentido


# Los filtros y el orden viven en la URL, no solo en la sesión. Pulsar una
# cabecera de tabla para ordenar es una navegación y recarga la página entera,
# y sin esto se perderían los filtros en cada clic. De paso, una vista concreta
# queda guardable como enlace.
FILTROS_EN_URL = ("pos", "equipo", "buscar", "mercado", "rango")


def guardar_en_url(param: str, valor, vacio) -> None:
    """Callback de widget: refleja su valor en la URL, o lo quita si está vacío."""
    if valor == vacio or valor is None or valor == "":
        st.query_params.pop(param, None)
    else:
        st.query_params[param] = str(valor)


def _sync(param: str, widget_key: str, vacio) -> None:
    guardar_en_url(param, st.session_state.get(widget_key), vacio)


def indice_en_url(param: str, opciones: list[str]) -> int:
    """Posición guardada en la URL dentro de una lista de opciones (0 si no hay)."""
    valor = st.query_params.get(param)
    return opciones.index(valor) if valor in opciones else 0


def style_chart(fig, title: str = "") -> None:
    """Aplica el tema del panel a una figura de Plotly.

    Plotly trae su propia tipografía, su rejilla y su caja de hover. Sin esto el
    gráfico sería lo único de la página que no pertenece al diseño.
    """
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title or "", font=dict(size=14, family="Barlow Condensed, sans-serif")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=ui.TOKENS["paper"],
        font=dict(family="Barlow, system-ui, sans-serif", size=13, color=ui.TOKENS["text"]),
        margin=dict(l=10, r=10, t=34, b=10),
        hoverlabel=dict(
            bgcolor=ui.TOKENS["ink"],
            bordercolor=ui.TOKENS["ink"],
            font=dict(family="Barlow, sans-serif", color="#FFFFFF", size=13),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, linecolor=ui.TOKENS["line"], ticks="outside", tickcolor=ui.TOKENS["line"])
    fig.update_yaxes(gridcolor=ui.TOKENS["line"], linecolor=ui.TOKENS["line"], zeroline=False)


def format_money(val: int | float | None, with_sign: bool = False) -> str:
    """Formatea cantidades monetarias en formato compacto estándar Fantasy: 900k, 130M, +1.5M, etc."""
    if val is None or pd.isna(val):
        return "—"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)

    sign = "+" if with_sign and val > 0 else ""
    abs_val = abs(val)

    if abs_val >= 1_000_000_000:
        num = val / 1_000_000_000
        formatted = f"{num:.1f}B" if not f"{num:.1f}".endswith(".0") else f"{num:.0f}B"
    elif abs_val >= 1_000_000:
        num = val / 1_000_000
        if abs_val >= 100_000_000 or abs(num - round(num)) < 1e-4:
            formatted = f"{round(num):.0f}M"
        elif abs(num * 10 - round(num * 10)) < 1e-3:
            formatted = f"{num:.1f}M"
        else:
            formatted = f"{num:.2f}M"
    elif abs_val >= 1_000:
        num = val / 1_000
        if abs_val >= 100_000 or abs(num - round(num)) < 1e-4:
            formatted = f"{round(num):.0f}k"
        elif abs(num * 10 - round(num * 10)) < 1e-3:
            formatted = f"{num:.1f}k"
        else:
            formatted = f"{num:.0f}k"
    else:
        formatted = f"{round(val):.0f}€"

    if with_sign and not formatted.startswith("-") and not formatted.startswith("+"):
        return f"{sign}{formatted}"
    return formatted


def acceso_permitido() -> bool:
    """Pide la contraseña si `APP_PASSWORD` está definida. Sin ella, acceso libre (local).

    La comparación es de tiempo constante para no dar pistas de cuánto acierta.
    Vale para toda la sesión del navegador: al recargar se vuelve a pedir.
    """
    if not config.APP_PASSWORD or st.session_state.get("acceso_ok"):
        return True
    render_html(ui.section("LaLiga Fantasy", "lock", "Panel privado. Introduce la contraseña para entrar."))
    with st.form("acceso"):
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(clave.encode("utf-8"), config.APP_PASSWORD.encode("utf-8")):
                st.session_state["acceso_ok"] = True
                st.rerun()
            st.error("Contraseña incorrecta.")
    return False


def main():
    # Inyectar estilos personalizados
    render_html(ui.CSS)

    if not acceso_permitido():
        st.stop()

    # Validar que Supabase esté configurado
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        st.error(
            "Faltan las variables de entorno de Supabase (`SUPABASE_URL` y `SUPABASE_SERVICE_KEY`).\n"
            "Configúralas en tu archivo `.env` para visualizar los datos."
        )
        st.stop()

    try:
        with st.spinner("Conectando con la base de datos de LaLiga Fantasy..."):
            df_players, df_teams = load_market_data()
            dates_available = [date.fromisoformat(f) for f in load_snapshot_dates()]
            df_daily = load_recent_daily(tuple(load_snapshot_dates()[-2:]))
            df_league_market = load_league_market()
            df_standings, df_movements, league_names = load_league_data(df_players)
            df_gw = load_gameweek_stats()
    except Exception as e:
        st.error(f"Error al conectar con Supabase: {e}")
        st.stop()

    # Si no hay datos todavía
    if df_players.empty or df_daily.empty:
        st.info(
            "**Aún no hay datos en la base de datos.**\n\n"
            "1. Asegúrate de haber ejecutado la migración DDL en Supabase (`db/migrations/001_init.sql`).\n"
            "2. Inicia sesión con `python scripts/login.py` (Apple, Google o email).\n"
            "3. Ejecuta el primer snapshot diario en tu terminal:\n"
            "   ```bash\n"
            "   python -m fantasy.collect.run_daily\n"
            "   ```"
        )
        return

    # Normalizar tipos
    df_daily["snapshot_date"] = pd.to_datetime(df_daily["snapshot_date"])
    num_days = len(dates_available)
    latest_date = dates_available[-1]

    # Procesar jugadores en mercado activo de la liga
    market_player_ids: set[str] = set()
    market_info_map: dict[str, dict] = {}
    if not df_league_market.empty:
        latest_mkt_date = df_league_market["snapshot_date"].max()
        df_cur_market = df_league_market[df_league_market["snapshot_date"] == latest_mkt_date].copy()
        for _, r in df_cur_market.iterrows():
            pid = str(r["player_id"]) if pd.notnull(r.get("player_id")) else ""
            if pid:
                market_player_ids.add(pid)
                market_info_map[pid] = {
                    "price": r.get("price"),
                    "expires_at": r.get("expires_at"),
                    "market_id": r.get("market_id"),
                }

    render_html(
        ui.masthead(
            "LaLiga Fantasy",
            [
                ("calendar", "Snapshot", str(latest_date)),
                ("chart", "Histórico", f"{num_days} días"),
                ("shirt", "Jugadores", f"{len(df_players)}"),
                ("pitch", "Equipos", f"{len(df_teams)}"),
            ],
        )
    )

    # Barra lateral de métricas y filtros
    st.sidebar.markdown("#### Filtros")

    # Mapeo de equipos
    teams_dict = dict(zip(df_teams["id"].astype(str), df_teams["name"]))
    df_players["team_name"] = df_players["team_id"].astype(str).map(teams_dict).fillna("Sin equipo")



    positions = ["Todas"] + sorted([p for p in df_players["position"].dropna().unique() if p])
    sel_position = st.sidebar.selectbox(
        "Posición",
        positions,
        index=indice_en_url("pos", positions),
        key="f_pos",
        on_change=lambda: _sync("pos", "f_pos", "Todas"),
    )

    team_list = ["Todos"] + sorted(df_players["team_name"].unique())
    sel_team = st.sidebar.selectbox(
        "Equipo",
        team_list,
        index=indice_en_url("equipo", team_list),
        key="f_equipo",
        on_change=lambda: _sync("equipo", "f_equipo", "Todos"),
    )

    df_latest = df_daily[df_daily["snapshot_date"].dt.date == latest_date].copy()
    max_market_val = int(df_latest["market_value"].dropna().max()) if not df_latest.empty else 100_000_000
    max_millones = max(1, -(-max_market_val // 1_000_000))

    rango_guardado = (0, max_millones)
    if "-" in st.query_params.get("rango", ""):
        try:
            desde_txt, hasta_txt = st.query_params["rango"].split("-", 1)
            rango_guardado = (
                max(0, min(max_millones, int(desde_txt))),
                max(0, min(max_millones, int(hasta_txt))),
            )
        except ValueError:
            rango_guardado = (0, max_millones)

    rango_millones = st.sidebar.slider(
        "Rango de valor",
        min_value=0,
        max_value=max_millones,
        value=rango_guardado,
        step=1,
        format="%d M",
        key="f_rango",
        help=f"El jugador más caro vale {format_money(max_market_val)}.",
        on_change=lambda: guardar_en_url(
            "rango",
            f"{st.session_state.f_rango[0]}-{st.session_state.f_rango[1]}",
            f"0-{max_millones}",
        ),
    )
    rango_precio = (rango_millones[0] * 1_000_000, rango_millones[1] * 1_000_000)

    search_query = st.sidebar.text_input(
        "Buscar jugador",
        value=st.query_params.get("buscar", ""),
        key="f_buscar",
        on_change=lambda: _sync("buscar", "f_buscar", ""),
    ).strip().lower()

    # Calcular variación si hay al menos 2 días de histórico
    has_variation = False
    if num_days >= 2:
        prev_date = dates_available[-2]
        df_prev = df_daily[df_daily["snapshot_date"].dt.date == prev_date].copy()
        merged_history = pd.merge(
            df_latest,
            df_prev[["player_id", "market_value"]],
            on="player_id",
            how="left",
            suffixes=("", "_prev"),
        )
        merged_history["diff_value"] = merged_history["market_value"] - merged_history["market_value_prev"]
        # Porcentaje de variación relativo al día anterior
        merged_history["pct_change"] = merged_history.apply(
            lambda r: (r["diff_value"] / r["market_value_prev"] * 100.0)
            if pd.notnull(r["market_value_prev"]) and r["market_value_prev"] > 0
            else None,
            axis=1,
        )
        df_market = pd.merge(df_players, merged_history, left_on="id", right_on="player_id", how="inner")
        has_variation = True
    else:
        df_market = pd.merge(df_players, df_latest, left_on="id", right_on="player_id", how="inner")
        df_market["diff_value"] = None
        df_market["pct_change"] = None

    # Añadir columna indicadora de mercado actual
    df_market["en_mercado"] = df_market["id"].astype(str).isin(market_player_ids)
    df_market["foto"] = df_market["image_url"].fillna(NO_PLAYER_IMG)
    df_market["fin_subasta"] = df_market["id"].astype(str).map(
        lambda pid: market_info_map.get(pid, {}).get("expires_at") if pid in market_info_map else None
    )

    # Aplicar filtros globales (posición, equipo, rango de precio, búsqueda)
    if sel_position != "Todas":
        df_market = df_market[df_market["position"] == sel_position]
    if sel_team != "Todos":
        df_market = df_market[df_market["team_name"] == sel_team]
    df_market = df_market[
        (df_market["market_value"].fillna(0) >= rango_precio[0])
        & (df_market["market_value"].fillna(0) <= rango_precio[1])
    ]
    if search_query:
        df_market = df_market[
            df_market["name"].str.lower().str.contains(search_query, na=False)
            | df_market["nickname"].str.lower().str.contains(search_query, na=False)
        ]

    # Pestañas principales
    tab_market, tab_evolution, tab_minutes, tab_squads, tab_league = st.tabs(
        [
            "Mercado",
            "Jugador",
            "Minutos",
            "Plantillas",
            "Liga privada",
        ]
    )

    # =========================================================================
    # PESTAÑA 1: MERCADO Y TENDENCIAS (MUY PRÁCTICO + FOTOS + RANKING + DINERO COMPACTO)
    # =========================================================================
    # Cada pestaña es un fragmento: así un clic dentro de ella (ordenar,
    # cambiar de jugador, mover el deslizador) solo la redibuja a ella y no
    # las otras tres, que Streamlit pintaría igualmente aunque no se vean.
    @st.fragment
    def _pestana_mercado():
        solo_mercado_tab = st.checkbox(
            "Solo lo que está en venta hoy en mi liga",
            value=st.query_params.get("mercado") == "1",
            key="f_mercado",
            help="Deja solo los futbolistas con puja abierta ahora mismo en tu liga privada.",
            on_change=lambda: guardar_en_url("mercado", "1" if st.session_state.f_mercado else "", ""),
        )

        df_view = df_market[df_market["en_mercado"]].copy() if solo_mercado_tab else df_market.copy()

        # Orden: se pulsa directamente en la cabecera de la tabla. Estos botones
        # están ocultos; el puente de arriba los pulsa por nosotros cuando se
        # hace clic en la cabecera, y así no hay recarga.
        with st.container(key="ordenadores"):
            for clave in ORDENES_MERCADO:
                st.button(clave, key=f"orden_{clave}", on_click=pulsar_orden, args=(clave,))
        components.html(PUENTE_ORDEN, height=0)

        orden, sentido = orden_actual_mercado(has_variation)
        df_sorted = df_view.sort_values(
            by=ORDENES_MERCADO[orden], ascending=(sentido == "asc"), na_position="last"
        )

        # Cifras de cabecera en una sola fila con filetes: cuatro tarjetas
        # idénticas serían el andamio perezoso, y aquí el protagonista es la tabla.
        total_mkt_active = len(df_view[df_view["en_mercado"]])
        df_valid_pct = df_view.dropna(subset=["pct_change"]) if has_variation else df_view.iloc[0:0]

        if has_variation and not df_valid_pct.empty:
            top_pct_up = df_valid_pct.sort_values(by="pct_change", ascending=False).iloc[0]
            top_eur_up = df_valid_pct.sort_values(by="diff_value", ascending=False).iloc[0]
            top_pct_down = df_valid_pct.sort_values(by="pct_change", ascending=True).iloc[0]
            render_html(
                ui.stat_row(
                    [
                        (
                            "Mayor subida %",
                            escape(str(top_pct_up["name"])),
                            f"{top_pct_up['pct_change']:+.2f}%".replace(".", ",")
                            + f" · {format_money(top_pct_up['diff_value'], with_sign=True)}",
                            "up",
                        ),
                        (
                            "Mayor subida €",
                            escape(str(top_eur_up["name"])),
                            format_money(top_eur_up["diff_value"], with_sign=True)
                            + f" · {top_eur_up['pct_change']:+.2f}%".replace(".", ","),
                            "up",
                        ),
                        (
                            "Mayor caída %",
                            escape(str(top_pct_down["name"])),
                            f"{top_pct_down['pct_change']:+.2f}%".replace(".", ",")
                            + f" · {format_money(top_pct_down['diff_value'], with_sign=True)}",
                            "down",
                        ),
                        ("En venta en tu liga", f"{total_mkt_active}", "con puja abierta", ""),
                    ]
                )
            )
        else:
            render_html(
                ui.stat_row(
                    [
                        ("En venta en tu liga", f"{len(market_player_ids)}", "con puja abierta", ""),
                        ("Jugadores", f"{len(df_players)}", "en la base de datos", ""),
                        ("Equipos", f"{len(df_teams)}", "de Primera", ""),
                        ("Histórico", f"{num_days}", "día registrado" if num_days == 1 else "días acumulados", ""),
                    ]
                )
            )



        if not has_variation:
            render_html(
                ui.notice(
                    "Con un solo día registrado no hay con qué comparar, así que todavía no se "
                    "puede calcular la variación. Aparece sola a partir del segundo snapshot."
                )
            )


        df_display = df_sorted.reset_index(drop=True)
        df_display["rank"] = df_display.index + 1

        # La barra dentro de la celda de variación se escala al mayor movimiento
        # de ESTA vista, no de toda la liga: lo que se compara es lo que se ve.
        max_abs_pct = 0.0
        if has_variation and df_display["pct_change"].notna().any():
            max_abs_pct = float(df_display["pct_change"].abs().max())

        LIMITE_FILAS = 250
        df_page = df_display.head(LIMITE_FILAS)

        columns = [
            {"label": "#", "align": "right", "cls": "rk hide-xs"},
            {"label": "Jugador", "align": "left", "sort": "jugador"},
            {"label": "Valor", "align": "right", "cls": "num", "sort": "valor"},
        ]
        if has_variation:
            columns.append({"label": "Variación", "align": "right", "sort": "variacion"})
        columns += [
            {"label": "Pts", "align": "right", "cls": "num", "sort": "puntos"},
            {"label": "Media", "align": "right", "cls": "num hide-sm", "sort": "media"},
            {"label": "Mercado", "align": "center", "cls": "hide-sm"},
        ]

        rows = []
        for _, r in df_page.iterrows():
            cells = [
                str(int(r["rank"])),
                ui.player_cell(
                    r["name"], r.get("team_name"), r.get("position"), r.get("image_url") or NO_PLAYER_IMG
                ),
                format_money(r.get("market_value")),
            ]
            if has_variation:
                pct = r.get("pct_change")
                pct_val = float(pct) if pd.notnull(pct) else None
                ratio = (abs(pct_val) / max_abs_pct) if (pct_val is not None and max_abs_pct) else 0.0
                cells.append(
                    ui.delta_cell(
                        format_money(r.get("diff_value"), with_sign=True), pct_val, ratio
                    )
                )
            cells += [
                format_points(r.get("points")),
                f"{r['average_points']:.2f}".replace(".", ",")
                if pd.notnull(r.get("average_points"))
                else '<span class="muted">—</span>',
                ui.tag("En venta", "live")
                if r.get("en_mercado")
                else '<span class="muted">—</span>',
            ]
            rows.append(cells)

        mostrados = len(df_page)
        de_mas = f" de {len(df_display)}" if len(df_display) > mostrados else ""
        render_html(
            ui.section(
                "Mercado",
                "wallet",
                f"{mostrados}{de_mas} futbolistas. Pulsa una cabecera para ordenar por esa columna.",
            )
        )
        # Los filtros se arrastran en el enlace de ordenación para no perderlos.
        arrastrar = urlencode(
            {k: v for k, v in st.query_params.to_dict().items() if k in FILTROS_EN_URL}
        )
        render_html(
            ui.data_table(
                columns,
                rows,
                sort={
                    "param": "orden",
                    "current": orden,
                    "dir": sentido,
                    "keep": f"{arrastrar}&" if arrastrar else "",
                },
            )
        )


    with tab_market:
        _pestana_mercado()

    # =========================================================================
    # PESTAÑA 2: EVOLUCIÓN Y RENDIMIENTO HISTÓRICO (GRÁFICAS INTERACTIVAS)
    # =========================================================================
    # Cada pestaña es un fragmento: así un clic dentro de ella (ordenar,
    # cambiar de jugador, mover el deslizador) solo la redibuja a ella y no
    # las otras tres, que Streamlit pintaría igualmente aunque no se vean.
    @st.fragment
    def _pestana_jugador():
        render_html(
            ui.section(
                "Ficha del jugador",
                "chart",
                "Puntos y minutos jornada a jornada, y la cotización acumulada desde que el panel registra datos.",
            )
        )

        player_options = df_players.set_index("id")["name"].to_dict()
        selected_player_id = st.selectbox(
            "Jugador",
            placeholder="Busca o elige un futbolista",
            options=list(player_options.keys()),
            format_func=lambda x: f"{player_options[x]} ({df_players[df_players['id'] == x]['team_name'].values[0]})",
        )

        if selected_player_id:
            df_p_history = load_player_history(str(selected_player_id))
            if not df_p_history.empty:
                df_p_history["snapshot_date"] = pd.to_datetime(df_p_history["snapshot_date"])
            df_p_gw = df_gw[df_gw["player_id"] == str(selected_player_id)].sort_values("gameweek")
            p_info = df_players[df_players["id"] == str(selected_player_id)].iloc[0]

            img_url = p_info.get("image_url") or NO_PLAYER_IMG
            is_on_sale = str(selected_player_id) in market_player_ids
            last_val = df_p_history.iloc[-1]["market_value"] if not df_p_history.empty else 0

            # Métricas agregadas
            tot_pts = int(df_p_gw["points"].sum()) if not df_p_gw.empty else 0
            avg_pts = float(df_p_gw["points"].mean()) if not df_p_gw.empty else 0.0
            tot_mins = int(df_p_gw["minutes"].sum()) if not df_p_gw.empty else 0
            tot_goals = int(df_p_gw["goals"].sum()) if not df_p_gw.empty else 0
            tot_saves = int(df_p_gw["saves"].sum()) if not df_p_gw.empty else 0

            render_html(
                ui.player_header(
                    p_info["name"],
                    p_info.get("team_name"),
                    p_info.get("position"),
                    img_url,
                    extra=ui.tag("En venta en tu liga", "live") if is_on_sale else "",
                )
            )
            render_html(
                ui.stat_row(
                    [
                        ("Valor", format_money(last_val), escape(str(p_info.get("status") or "").capitalize()), ""),
                        ("Puntos", f"{tot_pts}", f"media {avg_pts:.2f}".replace(".", ","), ""),
                        ("Minutos", f"{tot_mins}", f"en {len(df_p_gw)} jornadas", ""),
                        (
                            "Goles",
                            f"{tot_goals}",
                            f"{tot_saves} paradas" if tot_saves else "",
                            "",
                        ),
                    ]
                )
            )

            if not df_p_gw.empty:
                fig_gw = make_subplots(specs=[[{"secondary_y": True}]])
                fig_gw.add_trace(
                    go.Bar(
                        x=[f"J{gw}" for gw in df_p_gw["gameweek"]],
                        y=df_p_gw["points"],
                        name="Puntos",
                        marker_color=ui.TOKENS["ink"],
                        hovertemplate="<b>Jornada %{x}</b><br>%{y} puntos<extra></extra>",
                    ),
                    secondary_y=False,
                )
                fig_gw.add_trace(
                    go.Scatter(
                        x=[f"J{gw}" for gw in df_p_gw["gameweek"]],
                        y=df_p_gw["minutes"],
                        name="Minutos",
                        mode="lines+markers",
                        line=dict(color=ui.TOKENS["focus"], width=2),
                        marker=dict(size=6, color=ui.TOKENS["focus"]),
                        hovertemplate="%{y} min de 90<extra></extra>",
                    ),
                    secondary_y=True,
                )
                style_chart(fig_gw)
                fig_gw.update_yaxes(title_text="Puntos", secondary_y=False)
                fig_gw.update_yaxes(title_text="Minutos", range=[0, 105], secondary_y=True)
                st.plotly_chart(fig_gw, use_container_width=True)
            else:
                render_html(
                    ui.notice("Este futbolista no tiene todavía estadísticas por jornada registradas.")
                )

            if len(df_p_history) > 1:
                # El color de la curva dice si el jugador vale hoy más o menos que
                # el primer día registrado: la misma semántica que en la tabla.
                serie = df_p_history["market_value"]
                sube = float(serie.iloc[-1]) >= float(serie.iloc[0])
                color = ui.TOKENS["up"] if sube else ui.TOKENS["down"]
                relleno = ui.TOKENS["up_soft"] if sube else ui.TOKENS["down_soft"]
                fig_price = go.Figure()
                fig_price.add_trace(
                    go.Scatter(
                        x=df_p_history["snapshot_date"],
                        y=serie,
                        mode="lines",
                        name="Valor de mercado",
                        line=dict(color=color, width=2.5),
                        fill="tozeroy",
                        fillcolor=relleno,
                        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} €<extra></extra>",
                    )
                )
                style_chart(fig_price, "Cotización desde el primer snapshot")
                fig_price.update_yaxes(tickformat=",.0f", ticksuffix=" €")
                fig_price.update_layout(hovermode="x unified")
                st.plotly_chart(fig_price, use_container_width=True)
            else:
                render_html(
                    ui.notice(
                        f"Solo hay un snapshot de este jugador ({latest_date}), hoy vale "
                        f"<b>{format_money(last_val)}</b>. La curva de cotización se traza sola "
                        "según se acumulen días."
                    )
                )

            if not df_p_gw.empty:
                render_html(ui.section("Jornada a jornada", "pitch"))
                gw_columns = [
                    {"label": "J", "align": "right", "cls": "rk"},
                    {"label": "Puntos", "align": "right", "cls": "num"},
                    {"label": "Minutos", "align": "right", "cls": "num"},
                    {"label": "Goles", "align": "right", "cls": "num"},
                    {"label": "Asist.", "align": "right", "cls": "num hide-sm"},
                    {"label": "Paradas", "align": "right", "cls": "num hide-sm"},
                    {"label": "Encajados", "align": "right", "cls": "num hide-sm"},
                    {"label": "Tarjetas", "align": "right", "cls": "num hide-sm"},
                ]

                def _n(value) -> str:
                    return str(int(value)) if pd.notnull(value) else '<span class="muted">—</span>'

                gw_rows = []
                for _, g in df_p_gw.iterrows():
                    amarillas = int(g["yellow_cards"]) if pd.notnull(g.get("yellow_cards")) else 0
                    rojas = int(g["red_cards"]) if pd.notnull(g.get("red_cards")) else 0
                    if amarillas or rojas:
                        tarjetas = ui.tag(
                            ("R" if rojas else "A") + (f" x{amarillas}" if amarillas > 1 else ""),
                            "warn" if rojas else "neutral",
                        )
                    else:
                        tarjetas = '<span class="muted">—</span>'
                    gw_rows.append(
                        [
                            str(int(g["gameweek"])),
                            _n(g.get("points")),
                            _n(g.get("minutes")),
                            _n(g.get("goals")),
                            _n(g.get("assists")),
                            _n(g.get("saves")),
                            _n(g.get("goals_conceded")),
                            tarjetas,
                        ]
                    )
                render_html(ui.data_table(gw_columns, gw_rows, max_height="46vh"))


    with tab_evolution:
        _pestana_jugador()

    # =========================================================================
    # PESTAÑA 3: MINUTOS Y TITULARIDAD
    # =========================================================================
    # Cada pestaña es un fragmento: así un clic dentro de ella (ordenar,
    # cambiar de jugador, mover el deslizador) solo la redibuja a ella y no
    # las otras tres, que Streamlit pintaría igualmente aunque no se vean.
    @st.fragment
    def _pestana_minutos():
        render_html(
            ui.section(
                "Minutos y titularidad",
                "clock",
                "Ordenado por puntos conseguidos por cada millón de valor: arriba están los que más rinden para lo que cuestan. Solo futbolistas.",
            )
        )
        render_html(
            ui.notice(
                "Esto <b>no es una probabilidad de alineación</b>. No existe dato fiable de titularidad, "
                "así que se usan los minutos recientes como aproximación. Para pronósticos, "
                "FutbolFantasy o Jornada Perfecta.",
                icon_name="alert",
            )
        )

        if df_gw.empty:
            render_html(ui.notice("Todavía no hay estadísticas por jornada. Las rellena el snapshot diario."))
        else:
            max_gw = int(df_gw["gameweek"].max())
            ventana = st.slider(
                "Últimas jornadas a considerar",
                min_value=1,
                max_value=max_gw,
                value=min(5, max_gw),
            )
            desde = max_gw - ventana + 1
            df_win = df_gw[df_gw["gameweek"] >= desde]

            resumen = (
                df_win.groupby("player_id")
                .agg(
                    jornadas=("gameweek", "count"),
                    minutos=("minutes", "sum"),
                    puntos=("points", "sum"),
                    goles=("goals", "sum"),
                )
                .reset_index()
            )
            resumen["pct_minutos"] = (resumen["minutos"] / (ventana * 90) * 100).clip(upper=100)

            df_min = pd.merge(df_players, resumen, left_on="id", right_on="player_id", how="inner")
            df_min = pd.merge(
                df_min, df_latest[["player_id", "market_value"]], on="player_id", how="left"
            )
            df_min["pts_por_millon"] = df_min.apply(
                lambda r: (r["puntos"] / (r["market_value"] / 1_000_000))
                if pd.notnull(r.get("market_value")) and r["market_value"] > 0
                else None,
                axis=1,
            )
            # Fuera los entrenadores. No pisan el campo, así que salían con 0 minutos
            # y 0 puntos por millón, y un ranking de rendimiento sobre el césped no
            # dice nada de ellos: solo ensuciaba el final de la tabla.
            df_min = df_min[df_min["position"] != "Entrenador"]

            df_min["foto"] = df_min["image_url"].fillna(NO_PLAYER_IMG)
            df_min["valor_fmt"] = df_min["market_value"].apply(lambda v: format_money(v))

            if sel_position == "Entrenador":
                render_html(
                    ui.notice(
                        "Los entrenadores no salen en esta tabla: no juegan minutos, así que "
                        "medir su rendimiento por minuto jugado no significaría nada. "
                        "Sus puntos sí cuentan en el mercado."
                    )
                )
                return
            if sel_position != "Todas":
                df_min = df_min[df_min["position"] == sel_position]
            if sel_team != "Todos":
                df_min = df_min[df_min["team_name"] == sel_team]
            if search_query:
                df_min = df_min[df_min["name"].str.lower().str.contains(search_query, na=False)]

            solo_titulares = st.checkbox("Solo quien juega más del 60% de los minutos", value=False)
            if solo_titulares:
                df_min = df_min[df_min["pct_minutos"] > 60]

            df_min_display = df_min.sort_values("pts_por_millon", ascending=False).reset_index(drop=True)
            df_min_display["rank"] = df_min_display.index + 1

            min_columns = [
                {"label": "#", "align": "right", "cls": "rk hide-xs"},
                {"label": "Jugador", "align": "left"},
                {"label": "Valor", "align": "right", "cls": "num"},
                {"label": "Minutos", "align": "right", "cls": "num hide-sm"},
                {"label": "% jugado", "align": "right"},
                {"label": "Pts", "align": "right", "cls": "num hide-xs"},
                {"label": "Goles", "align": "right", "cls": "num hide-sm"},
                {"label": "Pts / M€", "align": "right", "cls": "num"},
            ]

            min_rows = []
            for _, r in df_min_display.head(250).iterrows():
                ppm = r.get("pts_por_millon")
                min_rows.append(
                    [
                        str(int(r["rank"])),
                        ui.player_cell(
                            r["name"], r.get("team_name"), r.get("position"), r.get("image_url") or NO_PLAYER_IMG
                        ),
                        format_money(r.get("market_value")),
                        f"{int(r['minutos'])}'" if pd.notnull(r.get("minutos")) else '<span class="muted">—</span>',
                        ui.bar_cell(float(r["pct_minutos"]) if pd.notnull(r.get("pct_minutos")) else None),
                        format_points(r.get("puntos")),
                        format_points(r.get("goles")),
                        f"{ppm:.2f}".replace(".", ",") if pd.notnull(ppm) else '<span class="muted">—</span>',
                    ]
                )
            render_html(ui.data_table(min_columns, min_rows))


    with tab_minutes:
        _pestana_minutos()

    # =========================================================================
    # PESTAÑA 4: PLANTILLAS Y CLÁUSULAS (CONSULTA EN VIVO)
    # =========================================================================
    # Cada pestaña es un fragmento: así un clic dentro de ella (ordenar,
    # cambiar de jugador, mover el deslizador) solo la redibuja a ella y no
    # las otras tres, que Streamlit pintaría igualmente aunque no se vean.
    @st.fragment
    def _pestana_plantillas():
        render_html(
            ui.section(
                "Plantillas y cláusulas",
                "shirt",
                "Quién tiene a quién, lo que cuesta su cláusula y a qué hora exacta se abre.",
            )
        )
        if "clausulazo_hecho" in st.session_state:
            st.success(st.session_state.pop("clausulazo_hecho"))

        ligas = sorted(league_names) or sorted(
            set(df_standings["league_id"].astype(str)) if not df_standings.empty else set()
        )
        if not ligas:
            render_html(ui.notice("No hay ligas detectadas todavía."))
            return

        liga_sel = ligas[0]
        if len(ligas) > 1:
            liga_sel = st.selectbox(
                "Liga",
                ligas,
                format_func=lambda x: league_names.get(x, x),
                key="liga_plantillas",
            )

        # La carga va a la API, no a Supabase, y cuesta unos segundos. Imponerla
        # en cada arranque devolvería la lentitud que se acaba de quitar, así que
        # se pide explícitamente y luego se queda en caché 90 segundos.
        if st.button("Consultar cláusulas ahora", type="primary", key="cargar_plantillas"):
            st.session_state["plantillas_pedidas"] = True

        if not st.session_state.get("plantillas_pedidas"):
            render_html(
                ui.notice(
                    "Las cláusulas son dato vivo: cambian de estado a una hora exacta, así que "
                    "no se guardan en la foto diaria. Pulsa el botón para consultarlas."
                )
            )
            return

        with st.spinner("Consultando las plantillas de la liga..."):
            try:
                df_squad, hora = load_squads(liga_sel)
            except Exception as e:
                render_html(
                    ui.notice(
                        f"No se pudieron leer las plantillas: {e}. "
                        "Si es un error de autenticación, vuelve a iniciar sesión.",
                        kind="warn",
                    )
                )
                return

        if df_squad.empty:
            render_html(ui.notice("La API no devolvió ninguna plantilla."))
            return

        df_squad["clause_locked_until"] = pd.to_datetime(
            df_squad["clause_locked_until"], errors="coerce", utc=True
        )
        ahora = datetime.now(timezone.utc)
        # `clause_open` viene calculado del modelo, pero la caché dura 90s y la
        # cuenta atrás se dibuja ahora: se recalcula para que no mienta.
        df_squad["abierta"] = (~df_squad["is_shielded"].astype(bool)) & (
            df_squad["clause_locked_until"].isna() | (df_squad["clause_locked_until"] <= ahora)
        )
        # Lo que de verdad decide un clausulazo: cuánto pagas de más sobre el
        # valor de mercado. Una cláusula igual al valor es una ganga.
        df_squad["sobrecoste"] = df_squad["buyout_clause"] - df_squad["market_value"]

        # Tus propios jugadores no se pueden clausular: no cuentan como abiertas.
        mi_equipo = load_my_teams().get(str(liga_sel))
        df_squad["es_mio"] = df_squad["league_team_id"].astype(str) == mi_equipo if mi_equipo else False

        abiertas = int((df_squad["abierta"] & ~df_squad["es_mio"]).sum())
        render_html(
            ui.stat_row(
                [
                    ("Jugadores", str(len(df_squad)), "en toda la liga", ""),
                    ("Mánagers", str(df_squad["manager_name"].nunique()), "con plantilla", ""),
                    ("Cláusulas abiertas", str(abiertas), "pagables ahora mismo", "up"),
                    ("Consultado", hora, "dato en vivo", ""),
                ]
            )
        )

        vista = st.radio(
            "Vista",
            ["Cláusulas abiertas", "Próximas a abrirse", "Por mánager"],
            horizontal=True,
            key="vista_plantillas",
            label_visibility="collapsed",
        )
        proximas = vista == "Próximas a abrirse"

        def sobrecoste_txt(sobre) -> str:
            if pd.notnull(sobre) and sobre > 0:
                return f'<span class="v-down">+{format_money(sobre)}</span>'
            if pd.notnull(sobre):
                return f'<span class="v-up">{format_money(sobre)}</span>'
            return MUTED_DASH

        def numero(valor, decimales: int = 0) -> str:
            if valor is None or pd.isna(valor):
                return MUTED_DASH
            return f"{valor:.{decimales}f}".replace(".", ",")

        if vista in ("Cláusulas abiertas", "Próximas a abrirse"):
            # Tus propios jugadores no se pueden clausular: fuera de las dos vistas.
            ajenas = df_squad[~df_squad["es_mio"]]
            if proximas:
                ventanas = {"6 h": 6, "24 h": 24, "48 h": 48, "7 días": 168, "Todas": None}
                ventana = st.select_slider(
                    "Se abren en las próximas",
                    options=list(ventanas),
                    value="48 h",
                    key="ventana_proximas",
                )
                base = proximas_a_abrirse(ajenas, ahora, ventanas[ventana])
                criterios = list(TODOS_CRITERIOS)
            else:
                base = ajenas[ajenas["abierta"]]
                criterios = list(CRITERIOS)
            df_base = enriquecer_clausulas(base, df_gw)

            c_crit, c_pres = st.columns([1, 1.4])
            with c_crit:
                criterio = st.selectbox(
                    "Ordenar por",
                    criterios,
                    format_func=lambda k: TODOS_CRITERIOS[k].etiqueta,
                    # Clave distinta por vista: cada una recuerda su orden.
                    key="criterio_proximas" if proximas else "criterio_clausulas",
                    help="El rendimiento por millón se calcula sobre la cláusula, que es lo que pagarías.",
                )
            with c_pres:
                # Escalones en millones: un deslizador de euros a secas no deja
                # elegir con precisión entre 2 M y 3 M cuando el máximo es 150 M.
                tope = df_base["buyout_clause"].max()
                escalones = [m * 1_000_000 for m in (1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200)]
                escalones = [e for e in escalones if pd.isna(tope) or e < tope] + [None]
                presupuesto = None
                if len(escalones) > 1:
                    presupuesto = st.select_slider(
                        "Cláusula máxima",
                        options=escalones,
                        value=None,
                        format_func=lambda e: "Sin límite" if e is None else format_money(e),
                        key="presupuesto_clausulas",
                    )
            solo_juegan = st.checkbox(
                f"Solo los que juegan (al menos {MIN_PCT_MINUTOS:.0f}% de los minutos en las "
                f"últimas {VENTANA_FORMA} jornadas)",
                value=True,
                key="solo_juegan_clausulas",
                help="Sin este filtro, un suplente de 0,3 M con dos apariciones encabeza los "
                "puntos por millón aunque no juegue nunca.",
            )
            df_v = ranking_clausulas(df_base, criterio, solo_juegan=solo_juegan, clausula_max=presupuesto)
            orden = TODOS_CRITERIOS[criterio].explicacion
            if proximas:
                cuando = "más adelante" if ventanas[ventana] is None else f"en las próximas {ventana}"
                nota = (
                    f"{len(df_v)} de {len(df_base)} cláusulas que se abren {cuando}, ordenadas por "
                    f"{orden}. Los blindados no salen: el escudo no tiene hora de fin."
                )
            else:
                nota = f"{len(df_v)} de {len(df_base)} cláusulas abiertas, ordenadas por {orden}."
        else:
            managers = sorted(df_squad["manager_name"].dropna().unique())
            quien = st.selectbox("Mánager", managers, key="manager_plantilla")
            df_v = df_squad[df_squad["manager_name"] == quien].copy()
            nota = f"{len(df_v)} jugadores en la plantilla de {quien}."
            df_v = df_v.sort_values(["position_id", "buyout_clause"], ascending=[True, False])

        if sel_position != "Todas":
            df_v = df_v[df_v["position"] == sel_position]
        if search_query:
            df_v = df_v[df_v["player_name"].str.lower().str.contains(search_query, na=False)]

        render_html(f'<p class="sc-n">{nota}</p>')

        if vista != "Por mánager":
            # Lo que sirve para decidir es cuánto rinde cada una por lo que cuesta. El
            # ratio que se enseña es el del criterio elegido, para que la cifra
            # explique el orden. En móvil quedan jugador, cláusula, ratio y, en las
            # próximas, la hora: el mánager pasa a la línea del equipo.
            ratio_col, ratio_label = (
                ("forma_por_millon", "Forma/M€") if criterio == "forma_millon" else ("pts_por_millon", "Pts/M€")
            )
            columnas = [
                {"label": "Jugador", "align": "left"},
                {"label": "Mánager", "align": "left", "cls": "hide-sm"},
                {"label": "Cláusula", "align": "right", "cls": "num"},
                {"label": "Sobrecoste", "align": "right", "cls": "num hide-sm"},
                {"label": "Puntos", "align": "right", "cls": "num hide-xs"},
                {"label": f"Forma {VENTANA_FORMA}J", "align": "right", "cls": "num hide-xs" if proximas else "num"},
                # En las próximas, en móvil manda la hora: el ratio cede su sitio.
                {"label": ratio_label, "align": "right", "cls": "num hide-xs" if proximas else "num"},
                {"label": f"Minutos {VENTANA_FORMA}J", "align": "left", "cls": "hide-sm"},
            ]
            if proximas:
                columnas.append({"label": "Se abre", "align": "right"})
            filas = []
            for _, r in df_v.head(200).iterrows():
                fila = [
                    ui.player_cell(
                        r["player_name"], r.get("club_name"), r.get("position"),
                        r.get("image_url") or NO_PLAYER_IMG, note=r.get("manager_name"),
                    ),
                    escape(str(r.get("manager_name") or "")),
                    format_money(r.get("buyout_clause")),
                    sobrecoste_txt(r.get("sobrecoste")),
                    numero(r.get("points")),
                    numero(r.get("forma")),
                    numero(r.get(ratio_col), 1),
                    ui.bar_cell(None if pd.isna(r.get("pct_minutos")) else r.get("pct_minutos")),
                ]
                if proximas:
                    fila.append(celda_apertura(r.get("clause_locked_until"), ahora))
                filas.append(fila)
        else:
            columnas = [
                {"label": "Jugador", "align": "left"},
                {"label": "Mánager", "align": "left", "cls": "hide-sm"},
                {"label": "Valor", "align": "right", "cls": "num hide-xs"},
                {"label": "Cláusula", "align": "right", "cls": "num"},
                {"label": "Sobrecoste", "align": "right", "cls": "num hide-xs"},
                {"label": "Se abre", "align": "right"},
            ]
            filas = [
                [
                    ui.player_cell(
                        r["player_name"], r.get("club_name"), r.get("position"),
                        r.get("image_url") or NO_PLAYER_IMG,
                    ),
                    escape(str(r.get("manager_name") or "")),
                    format_money(r.get("market_value")),
                    format_money(r.get("buyout_clause")),
                    sobrecoste_txt(r.get("sobrecoste")),
                    ui.tag("Escudo", "neutral")
                    if bool(r.get("is_shielded"))
                    else celda_apertura(r.get("clause_locked_until"), ahora),
                ]
                for _, r in df_v.head(200).iterrows()
            ]
        render_html(ui.data_table(columnas, filas))

        # Pago de una cláusula. Solo las que se pueden pagar ahora y no son tuyas; el
        # diálogo vuelve a comprobarla en vivo y pide confirmación antes de gastar.
        pagables = df_v[df_v["abierta"] & ~df_v["es_mio"] & df_v["player_team_id"].notna()].head(200)
        if not pagables.empty:
            render_html(
                ui.section(
                    "Pagar una cláusula",
                    "wallet",
                    "Antes de pagar se vuelve a comprobar la cláusula en vivo y se pide confirmación.",
                )
            )
            c_jug, c_btn = st.columns([3, 1], vertical_alignment="bottom")
            with c_jug:
                elegido = st.selectbox(
                    "Jugador",
                    list(pagables.index),
                    format_func=lambda i: (
                        f"{pagables.at[i, 'player_name']} · {pagables.at[i, 'manager_name']} · "
                        f"{format_money(pagables.at[i, 'buyout_clause'])}"
                    ),
                    key="jugador_clausulazo",
                )
            with c_btn:
                if st.button("Pagar cláusula…", key="abrir_clausulazo", use_container_width=True):
                    dialogo_clausulazo(str(liga_sel), pagables.loc[elegido].to_dict())


    with tab_squads:
        _pestana_plantillas()

    # =========================================================================
    # PESTAÑA 5: LIGA PRIVADA Y CAJA (FORMATO COMPACTO + CAJA ESTIMADA REAL)
    # =========================================================================
    # Cada pestaña es un fragmento: así un clic dentro de ella (ordenar,
    # cambiar de jugador, mover el deslizador) solo la redibuja a ella y no
    # las otras tres, que Streamlit pintaría igualmente aunque no se vean.
    @st.fragment
    def _pestana_liga():
        render_html(ui.section("Liga privada", "trophy"))

        # La cuenta puede tener varias ligas. Hay que separarlas antes de calcular nada:
        # la caja estimada suma movimientos, y mezclar los de dos ligas la falsearía.
        league_ids = set(league_names)
        if not df_standings.empty:
            league_ids |= set(df_standings["league_id"].astype(str))
        league_ids = sorted(league_ids)

        selected_league = None
        if len(league_ids) > 1:
            selected_league = st.selectbox(
                "Liga",
                league_ids,
                format_func=lambda league_id: league_names.get(league_id, f"Liga {league_id}"),
            )
        elif league_ids:
            selected_league = league_ids[0]
            render_html(
                f'<p class="lg-n">{escape(league_names.get(selected_league, f"Liga {selected_league}"))}</p>'
            )

        df_league_standings = (
            df_standings[df_standings["league_id"].astype(str) == selected_league]
            if selected_league and not df_standings.empty
            else pd.DataFrame()
        )
        df_league_movements = (
            df_movements[df_movements["league_id"].astype(str) == selected_league]
            if selected_league and not df_movements.empty
            else pd.DataFrame()
        )

        if df_league_standings.empty:
            render_html(ui.notice("Todavía no hay clasificación registrada de tu liga privada."))
        else:
            latest_league_date = df_league_standings["snapshot_date"].max()
            df_cur_standings = df_league_standings[df_league_standings["snapshot_date"] == latest_league_date].copy()

            if len(df_cur_standings) >= 3:
                top3 = df_cur_standings.sort_values("position").head(3).to_dict("records")
                render_html(
                    ui.podium(
                        [
                            {
                                "pos": int(t.get("position") or i + 1),
                                "team": t.get("team_name") or "—",
                                "manager": t.get("manager_name") or "Mánager",
                                "points": format_points(t.get("points")),
                                "value": format_money(t.get("team_value")),
                            }
                            for i, t in enumerate(top3)
                        ]
                    )
                )


            # La estimación de caja se retiró a petición del usuario. La API no
            # devuelve el saldo de los rivales, así que lo que se mostraba era una
            # reconstrucción a partir de los movimientos, no un dato. El cálculo
            # sigue en analytics/money.py por si vuelve a hacer falta.
            render_html(ui.section("Clasificación", "trophy"))

            cls_columns = [
                {"label": "#", "align": "right", "cls": "rk"},
                {"label": "Equipo", "align": "left"},
                {"label": "Pts", "align": "right", "cls": "num"},
                {"label": "Valor de plantilla", "align": "right", "cls": "num"},
            ]
            cls_rows = []
            for _, r in df_cur_standings.sort_values("position").iterrows():
                equipo_html = (
                    '<div class="pc-tx"><span class="pc-name">'
                    + escape(str(r.get("team_name") or "—"))
                    + '</span><span class="pc-team">'
                    + escape(str(r.get("manager_name") or "Mánager"))
                    + "</span></div>"
                )
                cls_rows.append(
                    [
                        format_points(r.get("position")),
                        equipo_html,
                        format_points(r.get("points")),
                        format_money(r.get("team_value")),
                    ]
                )
            render_html(ui.data_table(cls_columns, cls_rows, max_height="none"))

        if not df_league_movements.empty:
            # 881 movimientos serían 881 filas de HTML en cada redibujado. Se
            # muestran los últimos, que es lo que se mira; el resto sigue en la
            # base de datos y lo usa el análisis, no la vista.
            LIMITE_MOVIMIENTOS = 200
            df_mov_vista = df_league_movements.dropna(subset=["activity_desc"]).head(LIMITE_MOVIMIENTOS)
            total_mov = len(df_league_movements)
            nota_mov = (
                f"Los {LIMITE_MOVIMIENTOS} más recientes de {total_mov}."
                if total_mov > LIMITE_MOVIMIENTOS
                else f"{total_mov} movimientos registrados."
            )
            render_html(ui.section("Movimientos de la liga", "trend_up", nota_mov))

            # Un icono por tipo: entra dinero, sale dinero, o ninguna de las dos
            # cosas. Es lo primero que se busca al repasar la actividad de la liga.
            iconos_actividad = {1: "trend_down", 31: "trend_down", 2: "trend_up", 33: "trend_up", 6: "trophy"}

            mov_columns = [
                {"label": "Fecha", "align": "left", "cls": "hide-sm"},
                {"label": "Movimiento", "align": "left"},
                {"label": "Jugador", "align": "left"},
                {"label": "Mánager", "align": "left", "cls": "hide-sm"},
                {"label": "Importe", "align": "right", "cls": "num"},
            ]
            mov_rows = []
            for _, m in df_mov_vista.iterrows():
                tipo = m.get("activity_type")
                glyph = ui.icon(iconos_actividad.get(tipo, "dot"), 15, "mv-i")
                importe = m.get("amount")
                if pd.isna(importe):
                    importe_html = MUTED_DASH
                else:
                    tone = "up" if tipo in (2, 33, 6) else "down"
                    importe_html = f'<span class="mn mn-{tone}">{format_money(importe)}</span>'
                fecha = escape(str(m.get("movement_date_str") or "—"))
                desc = escape(str(m.get("activity_desc") or "—"))
                mov_rows.append(
                    [
                        f'<span class="muted">{fecha}</span>',
                        f'<span class="mv">{glyph}{desc}</span>',
                        escape(str(m.get("player_name") or "—")),
                        '<span class="muted">' + escape(str(m.get("manager_name") or "—")) + "</span>",
                        importe_html,
                    ]
                )
            render_html(ui.data_table(mov_columns, mov_rows, max_height="52vh"))



    with tab_league:
        _pestana_liga()

if __name__ == "__main__":
    main()
