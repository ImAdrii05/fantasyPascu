"""Panel de análisis de mercado de LaLiga Fantasy.

Este módulo decide QUÉ se muestra; el sistema de diseño vive en `ui.py` y decide
CÓMO se ve. Las tablas se componen como HTML propio en vez de `st.dataframe`
porque ésta no admite fotos, chips de demarcación ni cifras coloreadas, que es
justo lo que hace legible un listado de 800 jugadores.
"""

from datetime import date, datetime
from html import escape
from urllib.parse import urlencode
import textwrap
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from supabase import create_client

from fantasy import config
from fantasy.store.supabase import fetch_all
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


@st.cache_resource
def get_supabase_client():
    """Inicializa la conexión con Supabase con caché para evitar reconexiones."""
    config.validate_supabase_config()
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _df(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """DataFrame a partir de filas, con columnas garantizadas aunque venga vacío."""
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


@st.cache_data(ttl=300)
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

    daily = fetch_all(
        lambda: client.table("player_daily")
        .select("snapshot_date, player_id, market_value, points, average_points, played_matches, minutes_played")
        .order("snapshot_date")
        .order("player_id")
    )
    df_daily = _df(daily, ["snapshot_date", "player_id", "market_value", "points", "average_points", "played_matches", "minutes_played"])

    return df_players, df_daily, df_teams


@st.cache_data(ttl=300)
def load_league_market() -> pd.DataFrame:
    """Carga los jugadores actualmente listados en el mercado de la liga privada."""
    client = get_supabase_client()
    rows = fetch_all(
        lambda: client.table("league_market")
        .select("snapshot_date, league_id, market_id, player_id, price, owner_team_id, expires_at")
        .order("snapshot_date", desc=True)
    )
    return _df(rows, ["snapshot_date", "league_id", "market_id", "player_id", "price", "owner_team_id", "expires_at"])


@st.cache_data(ttl=300)
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


@st.cache_data(ttl=300)
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


def main():
    # Inyectar estilos personalizados
    render_html(ui.CSS)

    # Validar que Supabase esté configurado
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        st.error(
            "Faltan las variables de entorno de Supabase (`SUPABASE_URL` y `SUPABASE_SERVICE_KEY`).\n"
            "Configúralas en tu archivo `.env` para visualizar los datos."
        )
        st.stop()

    try:
        with st.spinner("Conectando con la base de datos de LaLiga Fantasy..."):
            df_players, df_daily, df_teams = load_market_data()
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
    dates_available = sorted(df_daily["snapshot_date"].dt.date.unique())
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
    tab_market, tab_evolution, tab_minutes, tab_league = st.tabs(
        [
            "Mercado",
            "Jugador",
            "Minutos",
            "Liga privada",
        ]
    )

    # =========================================================================
    # PESTAÑA 1: MERCADO Y TENDENCIAS (MUY PRÁCTICO + FOTOS + RANKING + DINERO COMPACTO)
    # =========================================================================
    with tab_market:
        solo_mercado_tab = st.checkbox(
            "Solo lo que está en venta hoy en mi liga",
            value=st.query_params.get("mercado") == "1",
            key="f_mercado",
            help="Deja solo los futbolistas con puja abierta ahora mismo en tu liga privada.",
            on_change=lambda: guardar_en_url("mercado", "1" if st.session_state.f_mercado else "", ""),
        )

        df_view = df_market[df_market["en_mercado"]].copy() if solo_mercado_tab else df_market.copy()

        # Orden: se pulsa directamente en la cabecera de la tabla.
        ORDENES = {
            "jugador": "name",
            "valor": "market_value",
            "variacion": "pct_change",
            "puntos": "points",
            "media": "average_points",
        }
        orden = st.query_params.get("orden", "variacion" if has_variation else "valor")
        if orden not in ORDENES or (orden == "variacion" and not has_variation):
            orden = "valor"
        sentido = st.query_params.get("dir")
        if sentido not in ("asc", "desc"):
            # Los nombres se leen de la A a la Z; todo lo demás, de mayor a menor.
            sentido = "asc" if orden == "jugador" else "desc"

        df_sorted = df_view.sort_values(
            by=ORDENES[orden], ascending=(sentido == "asc"), na_position="last"
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
            {"label": "#", "align": "right", "cls": "rk"},
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

    # =========================================================================
    # PESTAÑA 2: EVOLUCIÓN Y RENDIMIENTO HISTÓRICO (GRÁFICAS INTERACTIVAS)
    # =========================================================================
    with tab_evolution:
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
            df_p_history = df_daily[df_daily["player_id"] == str(selected_player_id)].sort_values("snapshot_date")
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

    # =========================================================================
    # PESTAÑA 3: MINUTOS Y TITULARIDAD
    # =========================================================================
    with tab_minutes:
        render_html(
            ui.section(
                "Minutos y titularidad",
                "clock",
                "Ordenado por puntos conseguidos por cada millón de valor: arriba están los que más rinden para lo que cuestan.",
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
            df_min["foto"] = df_min["image_url"].fillna(NO_PLAYER_IMG)
            df_min["valor_fmt"] = df_min["market_value"].apply(lambda v: format_money(v))

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
                {"label": "#", "align": "right", "cls": "rk"},
                {"label": "Jugador", "align": "left"},
                {"label": "Valor", "align": "right", "cls": "num"},
                {"label": "Minutos", "align": "right", "cls": "num hide-sm"},
                {"label": "% jugado", "align": "right"},
                {"label": "Pts", "align": "right", "cls": "num"},
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

    # =========================================================================
    # PESTAÑA 4: LIGA PRIVADA Y CAJA (FORMATO COMPACTO + CAJA ESTIMADA REAL)
    # =========================================================================
    with tab_league:
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
            render_html(ui.section("Movimientos de la liga", "trend_up"))

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
            for _, m in df_league_movements.dropna(subset=["activity_desc"]).iterrows():
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


if __name__ == "__main__":
    main()
