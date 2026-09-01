"""Dashboard interactivo para análisis de mercado de LaLiga Fantasy en Streamlit.

Lee EXCLUSIVAMENTE desde la base de datos de Supabase/Postgres.
NUNCA realiza peticiones en tiempo real a la API de LaLiga.
"""

from datetime import date
import streamlit as st
import pandas as pd
from supabase import create_client

from fantasy import config
from fantasy.store.supabase import fetch_all

# Configuración de página
st.set_page_config(
    page_title="LaLiga Fantasy — Dashboard Personal",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


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
    """Carga jugadores, snapshots diarios y equipos desde Supabase.

    Todas las lecturas van paginadas: PostgREST corta en 1000 filas SIN avisar, y
    `player_daily` supera ese techo al segundo día de histórico (813 filas/día).
    Sin paginar, el dashboard mostraría datos incompletos en silencio.
    """
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
    """Carga las estadísticas por jornada (minutos, goles, tarjetas...)."""
    client = get_supabase_client()
    rows = fetch_all(
        lambda: client.table("player_gameweek_stats")
        .select("player_id, gameweek, points, minutes, goals, assists, yellow_cards, red_cards, saves")
        .order("player_id")
        .order("gameweek")
    )
    return _df(rows, ["player_id", "gameweek", "points", "minutes", "goals", "assists", "yellow_cards", "red_cards", "saves"])


@st.cache_data(ttl=300)
def load_league_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga la clasificación y movimientos de la liga privada desde Supabase."""
    client = get_supabase_client()

    standings = fetch_all(
        lambda: client.table("league_standings").select("*").order("snapshot_date", desc=True).order("position")
    )
    df_standings = pd.DataFrame(standings) if standings else pd.DataFrame()

    movements_res = (
        client.table("league_movements").select("*").order("movement_date", desc=True).limit(100).execute()
    )
    df_movements = pd.DataFrame(movements_res.data) if movements_res.data else pd.DataFrame()

    return df_standings, df_movements


def main():
    st.title("⚽ LaLiga Fantasy — Análisis de Mercado")
    st.caption("Herramienta de análisis personal y seguimiento histórico de precios")

    # Validar que Supabase esté configurado
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        st.error(
            "⚠️ Faltan las variables de entorno de Supabase (`SUPABASE_URL` y `SUPABASE_SERVICE_KEY`).\n"
            "Configúralas en tu archivo `.env` para visualizar los datos."
        )
        st.stop()

    try:
        with st.spinner("Cargando datos históricos desde la base de datos..."):
            df_players, df_daily, df_teams = load_market_data()
            df_league_market = load_league_market()
            df_standings, df_movements = load_league_data()
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase: {e}")
        st.stop()

    # Si no hay datos todavía
    if df_players.empty or df_daily.empty:
        st.info(
            "ℹ️ **Aún no hay datos en la base de datos.**\n\n"
            "1. Asegúrate de haber ejecutado la migración DDL en Supabase (`db/migrations/001_init.sql`).\n"
            "2. Coloca tu token capturado en `secrets/token.json`.\n"
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

    # Barra lateral de métricas y filtros
    st.sidebar.header("📊 Resumen del Histórico")
    st.sidebar.metric("Snapshots acumulados", f"{num_days} días")
    st.sidebar.metric("Última actualización", str(latest_date))
    st.sidebar.metric("Total jugadores", len(df_players))
    st.sidebar.metric("En mercado de la liga", f"{len(market_player_ids)} jugadores")

    st.sidebar.divider()
    st.sidebar.header("Filtros de Mercado")

    # Mapeo de equipos
    teams_dict = dict(zip(df_teams["id"].astype(str), df_teams["name"]))
    df_players["team_name"] = df_players["team_id"].astype(str).map(teams_dict).fillna("Sin equipo")

    # Filtro por mercado actual en sidebar
    solo_mercado_sidebar = st.sidebar.checkbox(
        "🎯 Solo mercado actual",
        value=False,
        help="Muestra únicamente los jugadores que están a la venta hoy en tu liga privada.",
    )

    # Filtro por posición
    positions = ["Todas"] + sorted([p for p in df_players["position"].dropna().unique() if p])
    sel_position = st.sidebar.selectbox("Posición", positions)

    # Filtro por equipo
    team_list = ["Todos"] + sorted(df_players["team_name"].unique())
    sel_team = st.sidebar.selectbox("Equipo", team_list)

    # Búsqueda por texto
    search_query = st.sidebar.text_input("Buscar jugador", "").strip().lower()

    # Obtener el snapshot más reciente por jugador
    df_latest = df_daily[df_daily["snapshot_date"].dt.date == latest_date].copy()

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
    df_market["estado_mercado"] = df_market["en_mercado"].apply(lambda x: "🟢 EN VENTA" if x else "—")
    df_market["fin_subasta"] = df_market["id"].astype(str).map(
        lambda pid: market_info_map.get(pid, {}).get("expires_at") if pid in market_info_map else None
    )

    # Aplicar filtros globales (posición, equipo, búsqueda)
    if sel_position != "Todas":
        df_market = df_market[df_market["position"] == sel_position]
    if sel_team != "Todos":
        df_market = df_market[df_market["team_name"] == sel_team]
    if search_query:
        df_market = df_market[
            df_market["name"].str.lower().str.contains(search_query, na=False)
            | df_market["nickname"].str.lower().str.contains(search_query, na=False)
        ]

    # Pestañas principales
    tab_market, tab_evolution, tab_minutes, tab_league = st.tabs(
        ["💰 Mercado & Tendencias", "📈 Evolución de Precio", "⏱️ Minutos y Titularidad", "🏆 Liga Privada"]
    )

    # =========================================================================
    # PESTAÑA 1: MERCADO Y TENDENCIAS
    # =========================================================================
    with tab_market:
        st.subheader("💰 Análisis de Mercado y Variaciones de Precio")

        # Controles superiores: Checkbox de Mercado Actual y Selector de Vista
        col_chk, col_view = st.columns([1, 2])
        with col_chk:
            solo_mercado_tab = st.checkbox(
                "🎯 **Solo mercado actual** (en venta en mi liga)",
                value=solo_mercado_sidebar,
                key="chk_actual_mercado",
                help="Filtra la tabla para ver únicamente los jugadores que están a la venta hoy en tu liga privada.",
            )

        filter_active_market = solo_mercado_sidebar or solo_mercado_tab

        # Filtrar si está marcado el checkable
        df_view = df_market[df_market["en_mercado"]].copy() if filter_active_market else df_market.copy()

        if filter_active_market:
            st.caption(f"🔍 Mostrando **{len(df_view)}** jugadores a la venta en el mercado de tu liga.")

        # Si tenemos variación, mostrar KPIs de subidas/bajadas
        if has_variation:
            df_valid_pct = df_view.dropna(subset=["pct_change"])
            if not df_valid_pct.empty:
                top_pct_up = df_valid_pct.sort_values(by="pct_change", ascending=False).iloc[0]
                top_eur_up = df_valid_pct.sort_values(by="diff_value", ascending=False).iloc[0]
                top_pct_down = df_valid_pct.sort_values(by="pct_change", ascending=True).iloc[0]

                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                kpi1.metric(
                    "🚀 Mayor Subida (%)",
                    top_pct_up["name"],
                    f"{top_pct_up['pct_change']:+.2f} % ({top_pct_up['diff_value']:+,.0f} €)",
                )
                kpi2.metric(
                    "💶 Mayor Subida (€)",
                    top_eur_up["name"],
                    f"{top_eur_up['diff_value']:+,.0f} € ({top_eur_up['pct_change']:+.2f} %)",
                )
                kpi3.metric(
                    "🔻 Mayor Caída (%)",
                    top_pct_down["name"],
                    f"{top_pct_down['pct_change']:+.2f} % ({top_pct_down['diff_value']:+,.0f} €)",
                )
                kpi4.metric(
                    "🎯 En Mercado Activo",
                    f"{len(df_view[df_view['en_mercado']])} jugadores",
                )
                st.divider()

        with col_view:
            if has_variation:
                opciones_orden = [
                    "🚀 Que más suben en %",
                    "💶 Que más suben en €",
                    "🔻 Que más bajan en %",
                    "💎 Mayor valor de mercado",
                    "🏆 Más puntos",
                ]
                sel_orden = st.radio("Ordenar por:", opciones_orden, horizontal=True)
            else:
                opciones_orden = ["💎 Mayor valor de mercado", "🏆 Más puntos", "🔤 Nombre"]
                sel_orden = st.radio("Ordenar por:", opciones_orden, horizontal=True)

        if not has_variation:
            st.info(
                "💡 **Aún no hay histórico suficiente para calcular variación de precio.** "
                "Con un único día registrado se muestra el precio actual. La variación porcentual (% subida) "
                "comenzará a calcularse automáticamente a partir del segundo snapshot diario."
            )

        # Ordenar DataFrame según la opción seleccionada
        if has_variation:
            if sel_orden == "🚀 Que más suben en %":
                df_display = df_view.sort_values(by="pct_change", ascending=False)
            elif sel_orden == "💶 Que más suben en €":
                df_display = df_view.sort_values(by="diff_value", ascending=False)
            elif sel_orden == "🔻 Que más bajan en %":
                df_display = df_view.sort_values(by="pct_change", ascending=True)
            elif sel_orden == "💎 Mayor valor de mercado":
                df_display = df_view.sort_values(by="market_value", ascending=False)
            elif sel_orden == "🏆 Más puntos":
                df_display = df_view.sort_values(by="points", ascending=False)
            else:
                df_display = df_view.sort_values(by="market_value", ascending=False)
        else:
            if sel_orden == "💎 Mayor valor de mercado":
                df_display = df_view.sort_values(by="market_value", ascending=False)
            elif sel_orden == "🏆 Más puntos":
                df_display = df_view.sort_values(by="points", ascending=False)
            else:
                df_display = df_view.sort_values(by="name", ascending=True)

        # Formatear columnas para visualización
        display_cols = ["name", "nickname", "team_name", "position", "market_value", "points", "average_points", "estado_mercado"]
        if has_variation:
            display_cols = ["name", "nickname", "team_name", "position", "market_value", "pct_change", "diff_value", "points", "average_points", "estado_mercado"]

        col_config = {
            "name": st.column_config.TextColumn("Nombre"),
            "nickname": st.column_config.TextColumn("Apodo"),
            "team_name": st.column_config.TextColumn("Equipo"),
            "position": st.column_config.TextColumn("Posición"),
            "market_value": st.column_config.NumberColumn("Valor (€)", format="%d €"),
            "points": st.column_config.NumberColumn("Puntos"),
            "average_points": st.column_config.NumberColumn("Media", format="%.2f"),
            "estado_mercado": st.column_config.TextColumn("Mercado Liga"),
        }
        if has_variation:
            col_config["pct_change"] = st.column_config.NumberColumn("Subida (%)", format="%+.2f %%")
            col_config["diff_value"] = st.column_config.NumberColumn("Variación (€)", format="%+d €")

        st.dataframe(
            df_display[display_cols],
            column_config=col_config,
            use_container_width=True,
            hide_index=True,
        )

    # =========================================================================
    # PESTAÑA 2: EVOLUCIÓN TEMPORAL
    # =========================================================================
    with tab_evolution:
        st.subheader("Evolución del Valor de Mercado por Jugador")
        # Selector de jugador
        player_options = df_players.set_index("id")["name"].to_dict()
        selected_player_id = st.selectbox(
            "Selecciona un jugador para ver su histórico:",
            options=list(player_options.keys()),
            format_func=lambda x: f"{player_options[x]} ({df_players[df_players['id'] == x]['team_name'].values[0]})",
        )

        if selected_player_id:
            df_p_history = df_daily[df_daily["player_id"] == selected_player_id].sort_values("snapshot_date")
            p_info = df_players[df_players["id"] == selected_player_id].iloc[0]

            col_img, col_info = st.columns([1, 4])
            with col_img:
                if p_info.get("image_url"):
                    st.image(p_info["image_url"], width=120)
            with col_info:
                st.markdown(f"### {p_info['name']}")
                st.write(f"**Equipo:** {p_info['team_name']} | **Posición:** {p_info.get('position', 'N/A')}")
                if str(selected_player_id) in market_player_ids:
                    st.success("🟢 **Este jugador está actualmente a la venta en el mercado de tu liga.**")
                if not df_p_history.empty:
                    last_val = df_p_history.iloc[-1]["market_value"]
                    st.write(f"**Valor más reciente:** {last_val:,.0f} €" if last_val else "**Valor más reciente:** N/A")

            if len(df_p_history) > 1:
                chart_data = df_p_history.set_index("snapshot_date")["market_value"]
                st.line_chart(chart_data)
            else:
                st.info("Solo existe un registro diario para este jugador. El gráfico se trazará cuando se acumulen más días.")

    # =========================================================================
    # PESTAÑA 3: MINUTOS Y TITULARIDAD
    # =========================================================================
    with tab_minutes:
        st.subheader("Minutos recientes como proxy de titularidad")
        st.caption(
            "No existe un dato fiable de probabilidad de alineación, ni siquiera para LaLiga. "
            "Esto NO predice si un jugador será titular: solo muestra los minutos que ha jugado "
            "en las últimas jornadas, que es el mejor indicador objetivo disponible. Para una "
            "estimación de verdad, consulta fuentes curadas por humanos (Futbolfantasy, "
            "Jornada Perfecta, Analítica Fantasy)."
        )

        df_gw = load_gameweek_stats()
        if df_gw.empty:
            st.info("Todavía no hay estadísticas por jornada. Se rellenan con el snapshot diario.")
        else:
            max_gw = int(df_gw["gameweek"].max())
            ventana = st.slider(
                "Últimas N jornadas a considerar",
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
            # Porcentaje de minutos sobre el máximo posible (90 por jornada disputada).
            resumen["pct_minutos"] = (resumen["minutos"] / (ventana * 90) * 100).clip(upper=100)

            df_min = pd.merge(df_players, resumen, left_on="id", right_on="player_id", how="inner")
            df_min = pd.merge(
                df_min, df_latest[["player_id", "market_value"]], on="player_id", how="left"
            )
            # Puntos por millón: barato y productivo es exactamente lo que buscamos.
            df_min["pts_por_millon"] = df_min.apply(
                lambda r: (r["puntos"] / (r["market_value"] / 1_000_000))
                if r.get("market_value") and r["market_value"] > 0
                else None,
                axis=1,
            )

            if sel_position != "Todas":
                df_min = df_min[df_min["position"] == sel_position]
            if sel_team != "Todos":
                df_min = df_min[df_min["team_name"] == sel_team]
            if search_query:
                df_min = df_min[df_min["name"].str.lower().str.contains(search_query, na=False)]

            solo_titulares = st.checkbox("Solo jugadores con más del 60% de los minutos", value=False)
            if solo_titulares:
                df_min = df_min[df_min["pct_minutos"] > 60]

            st.dataframe(
                df_min[
                    ["name", "team_name", "position", "market_value", "minutos", "pct_minutos", "puntos", "goles", "pts_por_millon"]
                ].sort_values("pts_por_millon", ascending=False),
                column_config={
                    "name": st.column_config.TextColumn("Jugador"),
                    "team_name": st.column_config.TextColumn("Equipo"),
                    "position": st.column_config.TextColumn("Posición"),
                    "market_value": st.column_config.NumberColumn("Valor (€)", format="%d €"),
                    "minutos": st.column_config.NumberColumn("Minutos"),
                    "pct_minutos": st.column_config.ProgressColumn(
                        "% Minutos", min_value=0, max_value=100, format="%.0f%%"
                    ),
                    "puntos": st.column_config.NumberColumn("Puntos"),
                    "goles": st.column_config.NumberColumn("Goles"),
                    "pts_por_millon": st.column_config.NumberColumn("Pts / M€", format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
            )

    # =========================================================================
    # PESTAÑA 4: LIGA PRIVADA
    # =========================================================================
    with tab_league:
        st.subheader("Estado de la Liga Privada")
        if df_standings.empty:
            st.info("No hay datos de clasificación registrados para tu liga privada todavía.")
        else:
            latest_league_date = df_standings["snapshot_date"].max()
            st.write(f"Clasificación más reciente ({latest_league_date}):")
            df_cur_standings = df_standings[df_standings["snapshot_date"] == latest_league_date].copy()
            st.dataframe(
                df_cur_standings[["position", "team_name", "manager_name", "points", "team_value"]],
                column_config={
                    "position": st.column_config.NumberColumn("Posición"),
                    "team_name": st.column_config.TextColumn("Equipo"),
                    "manager_name": st.column_config.TextColumn("Mánager"),
                    "points": st.column_config.NumberColumn("Puntos"),
                    "team_value": st.column_config.NumberColumn("Valor de Plantilla (€)", format="%d €"),
                },
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "⚠️ La columna de valor es el precio de la PLANTILLA, no el dinero disponible. "
                "La API devuelve el saldo en caja de los rivales siempre a nulo (comprobado), "
                "así que no sabemos cuánto puede pujar cada uno. No lo deduzcas del valor de plantilla."
            )

        if not df_movements.empty:
            st.subheader("Últimos Movimientos de Mercado")
            st.dataframe(
                df_movements[["movement_date", "player_name", "amount", "movement_type"]],
                column_config={
                    "movement_date": st.column_config.DatetimeColumn("Fecha"),
                    "player_name": st.column_config.TextColumn("Jugador"),
                    "amount": st.column_config.NumberColumn("Importe (€)", format="%d €"),
                    "movement_type": st.column_config.TextColumn("Tipo"),
                },
                use_container_width=True,
                hide_index=True,
            )


if __name__ == "__main__":
    main()
