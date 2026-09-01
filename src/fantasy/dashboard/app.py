"""Dashboard interactivo para análisis de mercado de LaLiga Fantasy en Streamlit.

Diseño visual premium estilo Fantasy: Glassmorphism, Dark UI, fotos de futbolistas,
ranking 1..N, formato de dinero compacto (900k, 130M, etc.), badges de posición,
gráficos interactivos con Plotly de rendimiento histórico por jornada y cotización de mercado.
"""

from datetime import date, datetime
import textwrap
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from supabase import create_client

from fantasy import config
from fantasy.store.supabase import fetch_all
from fantasy.analytics.money import calculate_estimated_cash, suggest_initial_balance

# Configuración de página
st.set_page_config(
    page_title="LaLiga Fantasy — Pro Analytics",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_html(html_str: str) -> None:
    """Renderiza HTML nativo sin que Markdown lo confunda con bloques de código indentados."""
    st.html(textwrap.dedent(html_str).strip())


# =============================================================================
# ESTILOS CSS PERSONALIZADOS (THEME FANTASY DARK & NEON)
# =============================================================================
FANTASY_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', sans-serif;
}

h1, h2, h3, h4, .fantasy-font {
    font-family: 'Outfit', sans-serif;
    font-weight: 700;
    letter-spacing: -0.02em;
}

/* Header Banner */
.fantasy-hero {
    background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 27, 75, 0.9) 50%, rgba(15, 23, 42, 0.95) 100%);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 22px 28px;
    margin-bottom: 20px;
    box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
    position: relative;
    overflow: hidden;
}

.fantasy-hero::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 350px;
    height: 350px;
    background: radial-gradient(circle, rgba(239, 68, 68, 0.2) 0%, transparent 70%);
    pointer-events: none;
}

.hero-title {
    font-size: 2.1rem;
    font-weight: 800;
    background: linear-gradient(90deg, #ffffff 0%, #cbd5e1 50%, #f43f5e 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 12px;
}

.hero-subtitle {
    color: #94a3b8;
    font-size: 0.92rem;
    margin-top: 4px;
}

/* Stat Cards */
.stat-card {
    background: rgba(30, 41, 59, 0.7);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    transition: transform 0.2s ease, border-color 0.2s ease;
}

.stat-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.2);
}

.stat-card-title {
    color: #94a3b8;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}

.stat-card-value {
    color: #ffffff;
    font-size: 1.35rem;
    font-weight: 800;
    font-family: 'Outfit', sans-serif;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.stat-card-delta {
    font-size: 0.8rem;
    font-weight: 600;
    margin-top: 4px;
}

/* Position Badges */
.pos-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.pos-por { background: rgba(234, 179, 8, 0.15); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.3); }
.pos-def { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
.pos-med { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.pos-del { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.pos-ent { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }

/* Market status badge */
.badge-market-active {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.2) 0%, rgba(5, 150, 105, 0.3) 100%);
    border: 1px solid rgba(16, 185, 129, 0.4);
    color: #34d399;
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    box-shadow: 0 0 12px rgba(16, 185, 129, 0.2);
}

/* Player Mini Cards */
.player-highlight-card {
    background: linear-gradient(145deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.9) 100%);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 18px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3);
    position: relative;
    overflow: hidden;
    transition: all 0.25s ease;
}

.player-highlight-card:hover {
    transform: translateY(-4px);
    border-color: rgba(244, 63, 94, 0.4);
    box-shadow: 0 10px 30px rgba(244, 63, 94, 0.15);
}

.player-card-img {
    width: 68px;
    height: 68px;
    border-radius: 50%;
    object-fit: cover;
    background: rgba(255, 255, 255, 0.05);
    border: 2px solid rgba(255, 255, 255, 0.15);
}

.player-card-name {
    font-size: 1.05rem;
    font-weight: 700;
    color: #ffffff;
    margin-top: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.player-card-team {
    font-size: 0.8rem;
    color: #94a3b8;
}

.player-card-price {
    font-size: 1.15rem;
    font-weight: 800;
    color: #ffffff;
    font-family: 'Outfit', sans-serif;
    margin-top: 6px;
}

.pill-up {
    color: #34d399;
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.3);
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 700;
    display: inline-block;
}

.pill-down {
    color: #f87171;
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.3);
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 700;
    display: inline-block;
}

/* Custom Podium */
.podium-card {
    background: rgba(30, 41, 59, 0.8);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    border: 1px solid rgba(255, 255, 255, 0.1);
}
.podium-1 {
    border-color: rgba(234, 179, 8, 0.4);
    box-shadow: 0 0 25px rgba(234, 179, 8, 0.15);
    background: linear-gradient(180deg, rgba(234, 179, 8, 0.1) 0%, rgba(30, 41, 59, 0.9) 100%);
}
.podium-2 {
    border-color: rgba(203, 213, 225, 0.3);
}
.podium-3 {
    border-color: rgba(217, 119, 6, 0.3);
}
</style>
"""

NO_PLAYER_IMG = "https://assets-fantasy.llt-services.com/players/no-player/no-player-sq_256.png"


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
def load_league_data(df_players: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga la clasificación y movimientos enriquecidos de la liga privada."""
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
        1: "💰 Compra / Clausulazo",
        2: "🤝 Venta a rival",
        31: "🛒 Compra en mercado",
        33: "💸 Venta al mercado",
        6: "🏆 Premio de jornada",
        9: "📋 Alineación confirmada",
        10: "🔄 Cambio alineación",
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
    return df_standings, df_movements


def get_position_class(pos_name: str | None) -> str:
    """Devuelve la clase CSS correspondiente a cada posición."""
    if not pos_name:
        return "pos-badge pos-med"
    p = pos_name.lower()
    if "porter" in p or "por" in p:
        return "pos-badge pos-por"
    elif "def" in p:
        return "pos-badge pos-def"
    elif "med" in p or "centr" in p:
        return "pos-badge pos-med"
    elif "del" in p:
        return "pos-badge pos-del"
    return "pos-badge pos-ent"


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
    render_html(FANTASY_CSS)

    # Validar que Supabase esté configurado
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        st.error(
            "⚠️ Faltan las variables de entorno de Supabase (`SUPABASE_URL` y `SUPABASE_SERVICE_KEY`).\n"
            "Configúralas en tu archivo `.env` para visualizar los datos."
        )
        st.stop()

    try:
        with st.spinner("Conectando con la base de datos de LaLiga Fantasy..."):
            df_players, df_daily, df_teams = load_market_data()
            df_league_market = load_league_market()
            df_standings, df_movements = load_league_data(df_players)
            df_gw = load_gameweek_stats()
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

    # Header Hero Banner
    render_html(
        f"""
        <div class="fantasy-hero">
            <div class="hero-title">
                <span>⚽ LALIGA FANTASY</span>
                <span style="font-size: 0.8rem; font-weight: 800; background: #e11d48; color: #ffffff; padding: 4px 12px; border-radius: 9999px; letter-spacing: 0.05em; display: inline-block;">PRO ANALYTICS</span>
            </div>
            <div class="hero-subtitle">
                Seguimiento de mercado en vivo · Snapshots diarios · Estimación de caja y probabilidad de alineación
            </div>
        </div>
        """
    )

    # Barra lateral de métricas y filtros
    st.sidebar.markdown("### ⚙️ Centro de Control")
    st.sidebar.caption(f"📅 Snapshot activo: **{latest_date}** ({num_days} días acumulados)")

    # Mapeo de equipos
    teams_dict = dict(zip(df_teams["id"].astype(str), df_teams["name"]))
    df_players["team_name"] = df_players["team_id"].astype(str).map(teams_dict).fillna("Sin equipo")

    # Filtro por mercado actual en sidebar
    solo_mercado_sidebar = st.sidebar.checkbox(
        "🎯 **Solo mercado actual**",
        value=False,
        help="Muestra únicamente los jugadores que están a la venta hoy en tu liga privada.",
    )

    st.sidebar.divider()
    st.sidebar.markdown("### 🔍 Filtros Globales")

    # Filtro por posición
    positions = ["Todas"] + sorted([p for p in df_players["position"].dropna().unique() if p])
    sel_position = st.sidebar.selectbox("Posición", positions)

    # Filtro por equipo
    team_list = ["Todos"] + sorted(df_players["team_name"].unique())
    sel_team = st.sidebar.selectbox("Equipo", team_list)

    # Rango de precio
    df_latest = df_daily[df_daily["snapshot_date"].dt.date == latest_date].copy()
    max_market_val = int(df_latest["market_value"].dropna().max()) if not df_latest.empty else 100_000_000
    rango_precio = st.sidebar.slider(
        "Rango de Valor",
        min_value=0,
        max_value=max_market_val,
        value=(0, max_market_val),
        step=500_000,
        format="%d €",
        help=f"Filtra jugadores con valor hasta {format_money(max_market_val)}",
    )

    # Búsqueda por texto
    search_query = st.sidebar.text_input("Buscar jugador", "").strip().lower()

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
    df_market["foto"] = df_market["image_url"].fillna(NO_PLAYER_IMG)
    df_market["fin_subasta"] = df_market["id"].astype(str).map(
        lambda pid: market_info_map.get(pid, {}).get("expires_at") if pid in market_info_map else None
    )

    # Aplicar filtros globales (posición, equipo, rango de precio, búsqueda)
    if sel_position != "Todas":
        df_market = df_market[df_market["position"] == sel_position]
    if sel_team != "Todos":
        df_market = df_market[df_market["team_name"] == sel_team]
    if rango_precio:
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
            "💰 Mercado & Tendencias",
            "📈 Evolución y Rendimiento",
            "⏱️ Minutos y Titularidad",
            "🏆 Liga Privada & Caja",
        ]
    )

    # =========================================================================
    # PESTAÑA 1: MERCADO Y TENDENCIAS (MUY PRÁCTICO + FOTOS + RANKING + DINERO COMPACTO)
    # =========================================================================
    with tab_market:
        col_ctrl1, col_ctrl2 = st.columns([1.2, 2.8])
        with col_ctrl1:
            solo_mercado_tab = st.checkbox(
                "🎯 **Solo mercado actual** (en venta en mi liga)",
                value=solo_mercado_sidebar,
                key="chk_actual_mercado",
                help="Filtra para ver únicamente los jugadores que están a la venta hoy en tu liga privada.",
            )

        filter_active_market = solo_mercado_sidebar or solo_mercado_tab
        df_view = df_market[df_market["en_mercado"]].copy() if filter_active_market else df_market.copy()

        # Selector de ordenación dinámico y muy práctico
        with col_ctrl2:
            if has_variation:
                opciones_orden = [
                    "🚀 Mayor subida (%)",
                    "💶 Mayor subida (€)",
                    "💎 Mayor valor (€)",
                    "🔻 Mayor caída (%)",
                    "🏆 Más puntos",
                    "📈 Mejor media",
                    "🔤 Nombre (A-Z)",
                ]
            else:
                opciones_orden = [
                    "💎 Mayor valor (€)",
                    "🏆 Más puntos",
                    "📈 Mejor media",
                    "🔤 Nombre (A-Z)",
                ]
            sel_orden = st.radio("Ordenar ranking por:", opciones_orden, horizontal=True)

        # KPIs superiores estilizados con formato compacto
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        total_mkt_active = len(df_view[df_view["en_mercado"]])

        if has_variation:
            df_valid_pct = df_view.dropna(subset=["pct_change"])
            if not df_valid_pct.empty:
                top_pct_up = df_valid_pct.sort_values(by="pct_change", ascending=False).iloc[0]
                top_eur_up = df_valid_pct.sort_values(by="diff_value", ascending=False).iloc[0]
                top_pct_down = df_valid_pct.sort_values(by="pct_change", ascending=True).iloc[0]

                with kpi_c1:
                    render_html(
                        f"""
                        <div class="stat-card">
                            <div class="stat-card-title">🚀 Mayor Subida (%)</div>
                            <div class="stat-card-value" style="color: #34d399;">{top_pct_up['name']}</div>
                            <div class="stat-card-delta pill-up">+{top_pct_up['pct_change']:.2f} % ({format_money(top_pct_up['diff_value'], with_sign=True)})</div>
                        </div>
                        """
                    )
                with kpi_c2:
                    render_html(
                        f"""
                        <div class="stat-card">
                            <div class="stat-card-title">💶 Mayor Subida (€)</div>
                            <div class="stat-card-value" style="color: #60a5fa;">{top_eur_up['name']}</div>
                            <div class="stat-card-delta pill-up">{format_money(top_eur_up['diff_value'], with_sign=True)} (+{top_eur_up['pct_change']:.2f} %)</div>
                        </div>
                        """
                    )
                with kpi_c3:
                    render_html(
                        f"""
                        <div class="stat-card">
                            <div class="stat-card-title">🔻 Mayor Caída (%)</div>
                            <div class="stat-card-value" style="color: #f87171;">{top_pct_down['name']}</div>
                            <div class="stat-card-delta pill-down">{top_pct_down['pct_change']:.2f} % ({format_money(top_pct_down['diff_value'], with_sign=True)})</div>
                        </div>
                        """
                    )
                with kpi_c4:
                    render_html(
                        f"""
                        <div class="stat-card">
                            <div class="stat-card-title">🎯 En Mercado Activo</div>
                            <div class="stat-card-value" style="color: #facc15;">{total_mkt_active} <span style="font-size: 0.9rem; font-weight: 500; color: #94a3b8;">jugadores</span></div>
                            <div class="stat-card-delta" style="color: #94a3b8;">Disponibles para puja</div>
                        </div>
                        """
                    )
        else:
            with kpi_c1:
                render_html(
                    f"""
                    <div class="stat-card">
                        <div class="stat-card-title">🎯 En Mercado Activo</div>
                        <div class="stat-card-value" style="color: #34d399;">{len(market_player_ids)} <span style="font-size: 0.9rem; font-weight: 500; color: #94a3b8;">jugadores</span></div>
                        <div class="stat-card-delta" style="color: #94a3b8;">A la venta en tu liga</div>
                    </div>
                    """
                )
            with kpi_c2:
                render_html(
                    f"""
                    <div class="stat-card">
                        <div class="stat-card-title">👥 Total Jugadores</div>
                        <div class="stat-card-value" style="color: #60a5fa;">{len(df_players)}</div>
                        <div class="stat-card-delta" style="color: #94a3b8;">En la base de datos</div>
                    </div>
                    """
                )
            with kpi_c3:
                render_html(
                    f"""
                    <div class="stat-card">
                        <div class="stat-card-title">🛡️ Equipos</div>
                        <div class="stat-card-value" style="color: #facc15;">{len(df_teams)}</div>
                        <div class="stat-card-delta" style="color: #94a3b8;">Primera división</div>
                    </div>
                    """
                )
            with kpi_c4:
                render_html(
                    f"""
                    <div class="stat-card">
                        <div class="stat-card-title">📅 Snapshots</div>
                        <div class="stat-card-value" style="color: #c084fc;">{num_days} <span style="font-size: 0.9rem; font-weight: 500; color: #94a3b8;">día</span></div>
                        <div class="stat-card-delta" style="color: #94a3b8;">Día 1 registrado</div>
                    </div>
                    """
                )

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        # Destacados en tarjetas visuales (Top 4 del mercado activo)
        if filter_active_market and not df_view.empty:
            st.markdown("#### 🌟 Destacados en Venta Hoy")
            cols_top = st.columns(min(4, len(df_view)))
            top_sample = df_view.sort_values("market_value", ascending=False).head(4)
            for i, (_, row) in enumerate(top_sample.iterrows()):
                with cols_top[i]:
                    img_url = row.get("image_url") or NO_PLAYER_IMG
                    pos_cls = get_position_class(row.get("position"))
                    pct_str = f"+{row['pct_change']:.2f}%" if pd.notnull(row.get("pct_change")) and row["pct_change"] > 0 else (f"{row['pct_change']:.2f}%" if pd.notnull(row.get("pct_change")) else "Activo")
                    render_html(
                        f"""
                        <div class="player-highlight-card">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span class="{pos_cls}">{row.get('position', 'JUG')}</span>
                                <span class="badge-market-active">🟢 EN VENTA</span>
                            </div>
                            <div style="text-align: center; margin-top: 8px;">
                                <img src="{img_url}" class="player-card-img" />
                                <div class="player-card-name">{row['name']}</div>
                                <div class="player-card-team">{row['team_name']}</div>
                                <div class="player-card-price">{format_money(row['market_value'])}</div>
                                <div style="margin-top: 6px;"><span class="pill-up">{pct_str}</span></div>
                            </div>
                        </div>
                        """
                    )
            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        if not has_variation:
            st.info(
                "💡 **Aún no hay histórico suficiente para calcular variación temporal.** "
                "Con un único día registrado se muestra el precio actual. Las variaciones porcentuales (% subida) "
                "se calcularán automáticamente a partir del segundo snapshot diario."
            )

        # ORDENACIÓN DEL RANKING
        if has_variation:
            if sel_orden == "🚀 Mayor subida (%)":
                df_sorted = df_view.sort_values(by="pct_change", ascending=False, na_position="last")
            elif sel_orden == "💶 Mayor subida (€)":
                df_sorted = df_view.sort_values(by="diff_value", ascending=False, na_position="last")
            elif sel_orden == "💎 Mayor valor (€)":
                df_sorted = df_view.sort_values(by="market_value", ascending=False, na_position="last")
            elif sel_orden == "🔻 Mayor caída (%)":
                df_sorted = df_view.sort_values(by="pct_change", ascending=True, na_position="last")
            elif sel_orden == "🏆 Más puntos":
                df_sorted = df_view.sort_values(by="points", ascending=False, na_position="last")
            elif sel_orden == "📈 Mejor media":
                df_sorted = df_view.sort_values(by="average_points", ascending=False, na_position="last")
            else:
                df_sorted = df_view.sort_values(by="name", ascending=True)
        else:
            if sel_orden == "💎 Mayor valor (€)":
                df_sorted = df_view.sort_values(by="market_value", ascending=False, na_position="last")
            elif sel_orden == "🏆 Más puntos":
                df_sorted = df_view.sort_values(by="points", ascending=False, na_position="last")
            elif sel_orden == "📈 Mejor media":
                df_sorted = df_view.sort_values(by="average_points", ascending=False, na_position="last")
            else:
                df_sorted = df_view.sort_values(by="name", ascending=True)

        # Generar columna de ranking 1, 2, 3, 4, 5... y formato compacto de dinero (900k, 130M...)
        df_display = df_sorted.reset_index(drop=True)
        df_display["rank"] = df_display.index + 1
        df_display["valor_fmt"] = df_display["market_value"].apply(lambda v: format_money(v))
        if has_variation:
            df_display["diff_fmt"] = df_display["diff_value"].apply(lambda v: format_money(v, with_sign=True))

        # Columnas a mostrar
        display_cols = ["rank", "foto", "name", "nickname", "team_name", "position", "valor_fmt", "points", "average_points", "estado_mercado"]
        if has_variation:
            display_cols = ["rank", "foto", "name", "nickname", "team_name", "position", "valor_fmt", "pct_change", "diff_fmt", "points", "average_points", "estado_mercado"]

        col_config = {
            "rank": st.column_config.NumberColumn("#", help="Posición en el ranking", format="%d", width="small"),
            "foto": st.column_config.ImageColumn("Foto", help="Foto del futbolista", width="small"),
            "name": st.column_config.TextColumn("Nombre"),
            "nickname": st.column_config.TextColumn("Apodo"),
            "team_name": st.column_config.TextColumn("Equipo"),
            "position": st.column_config.TextColumn("Posición"),
            "valor_fmt": st.column_config.TextColumn("Valor", help="Valor de mercado en formato compacto (k/M)"),
            "pct_change": st.column_config.NumberColumn("Subida (%)", format="%+.2f %%"),
            "diff_fmt": st.column_config.TextColumn("Variación (€)", help="Variación en dinero compacto (k/M)"),
            "points": st.column_config.NumberColumn("Puntos"),
            "average_points": st.column_config.NumberColumn("Media", format="%.2f"),
            "estado_mercado": st.column_config.TextColumn("Mercado Liga"),
        }

        st.caption(f"📋 Mostrando **{len(df_display)}** futbolistas ordenados por **{sel_orden}**")
        st.dataframe(
            df_display[display_cols],
            column_config=col_config,
            use_container_width=True,
            hide_index=True,
            height=600,
        )

    # =========================================================================
    # PESTAÑA 2: EVOLUCIÓN Y RENDIMIENTO HISTÓRICO (GRÁFICAS INTERACTIVAS)
    # =========================================================================
    with tab_evolution:
        st.subheader("📈 Rendimiento Histórico por Jornada y Cotización")

        player_options = df_players.set_index("id")["name"].to_dict()
        selected_player_id = st.selectbox(
            "Selecciona un jugador para analizar:",
            options=list(player_options.keys()),
            format_func=lambda x: f"{player_options[x]} ({df_players[df_players['id'] == x]['team_name'].values[0]})",
        )

        if selected_player_id:
            df_p_history = df_daily[df_daily["player_id"] == str(selected_player_id)].sort_values("snapshot_date")
            df_p_gw = df_gw[df_gw["player_id"] == str(selected_player_id)].sort_values("gameweek")
            p_info = df_players[df_players["id"] == str(selected_player_id)].iloc[0]

            img_url = p_info.get("image_url") or NO_PLAYER_IMG
            pos_cls = get_position_class(p_info.get("position"))
            is_on_sale = str(selected_player_id) in market_player_ids
            mkt_badge_html = '<span class="badge-market-active" style="margin-left: 8px;">🟢 EN VENTA EN TU LIGA</span>' if is_on_sale else ""
            last_val = df_p_history.iloc[-1]["market_value"] if not df_p_history.empty else 0

            # Métricas agregadas
            tot_pts = int(df_p_gw["points"].sum()) if not df_p_gw.empty else 0
            avg_pts = float(df_p_gw["points"].mean()) if not df_p_gw.empty else 0.0
            tot_mins = int(df_p_gw["minutes"].sum()) if not df_p_gw.empty else 0
            tot_goals = int(df_p_gw["goals"].sum()) if not df_p_gw.empty else 0
            tot_saves = int(df_p_gw["saves"].sum()) if not df_p_gw.empty else 0

            col_pcard, col_pchart = st.columns([1, 2])

            with col_pcard:
                render_html(
                    f"""
                    <div class="player-highlight-card">
                        <div style="display: flex; align-items: center; gap: 16px;">
                            <img src="{img_url}" class="player-card-img" style="width: 80px; height: 80px;" />
                            <div>
                                <div style="display: flex; align-items: center;">
                                    <span class="{pos_cls}">{p_info.get('position', 'JUG')}</span>
                                    {mkt_badge_html}
                                </div>
                                <div style="font-size: 1.3rem; font-weight: 800; color: white; margin-top: 4px;">{p_info['name']}</div>
                                <div style="color: #94a3b8; font-size: 0.9rem;">{p_info['team_name']}</div>
                            </div>
                        </div>
                        <hr style="border: 0; border-top: 1px solid rgba(255, 255, 255, 0.08); margin: 14px 0;" />
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                            <div>
                                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Valor Actual</div>
                                <div style="font-size: 1.25rem; font-weight: 800; color: #ffffff;">{format_money(last_val)}</div>
                            </div>
                            <div>
                                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Estado</div>
                                <div style="font-size: 1rem; font-weight: 700; color: #34d399;">{p_info.get('status', 'OK')}</div>
                            </div>
                            <div>
                                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Puntos Totales</div>
                                <div style="font-size: 1.15rem; font-weight: 800; color: #f43f5e;">{tot_pts} pts</div>
                            </div>
                            <div>
                                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Media / Jornada</div>
                                <div style="font-size: 1.15rem; font-weight: 800; color: #60a5fa;">{avg_pts:.2f}</div>
                            </div>
                        </div>
                    </div>
                    """
                )

            with col_pchart:
                if not df_p_gw.empty:
                    # GRÁFICA DE RENDIMIENTO POR JORNADA (PUNTOS Y MINUTOS)
                    fig_gw = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_gw.add_trace(
                        go.Bar(
                            x=[f"J{gw}" for gw in df_p_gw["gameweek"]],
                            y=df_p_gw["points"],
                            name="Puntos Fantasy",
                            marker_color="#f43f5e",
                            text=df_p_gw["points"],
                            textposition="outside",
                            hovertemplate="<b>Jornada %{x}</b><br>Puntos: %{y}<extra></extra>",
                        ),
                        secondary_y=False,
                    )
                    fig_gw.add_trace(
                        go.Scatter(
                            x=[f"J{gw}" for gw in df_p_gw["gameweek"]],
                            y=df_p_gw["minutes"],
                            name="Minutos Jugados",
                            mode="lines+markers",
                            line=dict(color="#38bdf8", width=3),
                            marker=dict(size=8, color="#38bdf8", line=dict(color="#ffffff", width=1.5)),
                            hovertemplate="Minutos: %{y}' / 90'<extra></extra>",
                        ),
                        secondary_y=True,
                    )
                    fig_gw.update_layout(
                        template="plotly_dark",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(30, 41, 59, 0.4)",
                        margin=dict(l=20, r=20, t=30, b=20),
                        title="📊 Puntos y Minutos por Jornada",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    fig_gw.update_yaxes(title_text="Puntos", secondary_y=False)
                    fig_gw.update_yaxes(title_text="Minutos", range=[0, 105], secondary_y=True)
                    st.plotly_chart(fig_gw, use_container_width=True)
                else:
                    st.info("No hay estadísticas por jornada registradas para este futbolista.")

            # Gráfica de cotización de valor de mercado si hay histórico diario
            st.markdown("#### 💰 Histórico de Cotización de Mercado")
            if len(df_p_history) > 1:
                fig_price = go.Figure()
                fig_price.add_trace(
                    go.Scatter(
                        x=df_p_history["snapshot_date"],
                        y=df_p_history["market_value"],
                        mode="lines+markers",
                        name="Valor de Mercado",
                        line=dict(color="#10b981", width=3, shape="spline"),
                        marker=dict(size=6, color="#10b981", line=dict(color="#ffffff", width=1.5)),
                        fill="tozeroy",
                        fillcolor="rgba(16, 185, 129, 0.1)",
                        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Valor: %{y:$,d} €<extra></extra>",
                    )
                )
                fig_price.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(30, 41, 59, 0.4)",
                    margin=dict(l=20, r=20, t=20, b=20),
                    yaxis=dict(title="Valor", tickformat="$,d"),
                    xaxis=dict(title="Fecha", showgrid=False),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_price, use_container_width=True)
            else:
                st.caption(
                    f"📅 **Snapshot del día {latest_date}:** Cotización actual **{format_money(last_val)}**. "
                    "La curva continua de precio trazará la serie temporal acumulada con cada snapshot diario automático."
                )

            # Desglose en tabla jornada a jornada
            if not df_p_gw.empty:
                st.markdown("#### 📋 Desglose Detallado por Jornada")
                gw_cols = ["gameweek", "points", "minutes", "goals", "assists", "saves", "goals_conceded", "yellow_cards", "red_cards"]
                st.dataframe(
                    df_p_gw[gw_cols],
                    column_config={
                        "gameweek": st.column_config.NumberColumn("Jornada", format="J%d"),
                        "points": st.column_config.NumberColumn("Puntos", format="%d pts"),
                        "minutes": st.column_config.NumberColumn("Minutos", format="%d'"),
                        "goals": st.column_config.NumberColumn("Goles"),
                        "assists": st.column_config.NumberColumn("Asistencias"),
                        "saves": st.column_config.NumberColumn("Paradas"),
                        "goals_conceded": st.column_config.NumberColumn("Goles Encajados"),
                        "yellow_cards": st.column_config.NumberColumn("Amarillas"),
                        "red_cards": st.column_config.NumberColumn("Rojas"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

    # =========================================================================
    # PESTAÑA 3: MINUTOS Y TITULARIDAD
    # =========================================================================
    with tab_minutes:
        st.subheader("⏱️ Minutos Recientes como Proxy de Titularidad")
        st.caption(
            "La regularidad de minutos disputados en las últimas jornadas es el mejor indicador objetivo disponible. "
            "Para predicciones avanzadas, consulta fuentes especializadas (Futbolfantasy, Jornada Perfecta)."
        )

        if df_gw.empty:
            st.info("Todavía no hay estadísticas por jornada registradas. Se rellenan con el snapshot diario.")
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

            solo_titulares = st.checkbox("Solo jugadores con más del 60% de los minutos", value=False)
            if solo_titulares:
                df_min = df_min[df_min["pct_minutos"] > 60]

            df_min_display = df_min.sort_values("pts_por_millon", ascending=False).reset_index(drop=True)
            df_min_display["rank"] = df_min_display.index + 1

            st.dataframe(
                df_min_display[
                    ["rank", "foto", "name", "team_name", "position", "valor_fmt", "minutos", "pct_minutos", "puntos", "goles", "pts_por_millon"]
                ],
                column_config={
                    "rank": st.column_config.NumberColumn("#", format="%d", width="small"),
                    "foto": st.column_config.ImageColumn("Foto", width="small"),
                    "name": st.column_config.TextColumn("Jugador"),
                    "team_name": st.column_config.TextColumn("Equipo"),
                    "position": st.column_config.TextColumn("Posición"),
                    "valor_fmt": st.column_config.TextColumn("Valor"),
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
    # PESTAÑA 4: LIGA PRIVADA Y CAJA (FORMATO COMPACTO + CAJA ESTIMADA REAL)
    # =========================================================================
    with tab_league:
        st.subheader("🏆 Clasificación y Estimación de Caja de Rivales")

        if df_standings.empty:
            st.info("No hay datos de clasificación registrados para tu liga privada todavía.")
        else:
            latest_league_date = df_standings["snapshot_date"].max()
            df_cur_standings = df_standings[df_standings["snapshot_date"] == latest_league_date].copy()

            # Podium para los 3 primeros con formato compacto
            if len(df_cur_standings) >= 3:
                top3 = df_cur_standings.sort_values("position").head(3).to_dict("records")
                c_p2, c_p1, c_p3 = st.columns([1, 1.2, 1])

                with c_p1:
                    render_html(
                        f"""
                        <div class="podium-card podium-1">
                            <div style="font-size: 2rem;">🥇</div>
                            <div style="font-size: 1.3rem; font-weight: 800; color: #facc15;">{top3[0]['team_name']}</div>
                            <div style="color: #cbd5e1; font-size: 0.9rem;">{top3[0].get('manager_name', 'Mánager')}</div>
                            <div style="font-size: 1.5rem; font-weight: 800; color: white; margin-top: 8px;">{top3[0].get('points', 0)} pts</div>
                            <div style="color: #94a3b8; font-size: 0.85rem;">Plantilla: {format_money(top3[0].get('team_value'))}</div>
                        </div>
                        """
                    )
                with c_p2:
                    render_html(
                        f"""
                        <div class="podium-card podium-2" style="margin-top: 24px;">
                            <div style="font-size: 1.7rem;">🥈</div>
                            <div style="font-size: 1.15rem; font-weight: 700; color: #e2e8f0;">{top3[1]['team_name']}</div>
                            <div style="color: #94a3b8; font-size: 0.85rem;">{top3[1].get('manager_name', 'Mánager')}</div>
                            <div style="font-size: 1.3rem; font-weight: 800; color: white; margin-top: 6px;">{top3[1].get('points', 0)} pts</div>
                            <div style="color: #94a3b8; font-size: 0.8rem;">Plantilla: {format_money(top3[1].get('team_value'))}</div>
                        </div>
                        """
                    )
                with c_p3:
                    render_html(
                        f"""
                        <div class="podium-card podium-3" style="margin-top: 36px;">
                            <div style="font-size: 1.5rem;">🥉</div>
                            <div style="font-size: 1.1rem; font-weight: 700; color: #d97706;">{top3[2]['team_name']}</div>
                            <div style="color: #94a3b8; font-size: 0.85rem;">{top3[2].get('manager_name', 'Mánager')}</div>
                            <div style="font-size: 1.2rem; font-weight: 800; color: white; margin-top: 6px;">{top3[2].get('points', 0)} pts</div>
                            <div style="color: #94a3b8; font-size: 0.8rem;">Plantilla: {format_money(top3[2].get('team_value'))}</div>
                        </div>
                        """
                    )

            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

            # Estimación de caja por movimientos
            cajas_estimadas = calculate_estimated_cash(df_cur_standings, df_movements)
            if not cajas_estimadas.empty:
                st.markdown("#### 💰 Estimación de Caja Disponible")
                st.caption(
                    "Calculada a partir del saldo inicial y el flujo neto acumulado de fichajes, ventas y premios. "
                    "Las diferencias relativas entre mánagers son exactas."
                )

                # Unir por team_id o manager_id de forma robusta
                df_tabla_caja = pd.merge(
                    df_cur_standings[["league_team_id", "position", "team_name", "manager_name", "points", "team_value"]],
                    cajas_estimadas[["team_id", "cash_estimate", "net_transfer_flow", "prize_flow", "movements_count"]],
                    left_on="league_team_id",
                    right_on="team_id",
                    how="left",
                )

                df_tabla_caja["team_value_fmt"] = df_tabla_caja["team_value"].apply(lambda v: format_money(v))
                df_tabla_caja["cash_estimate_fmt"] = df_tabla_caja["cash_estimate"].apply(lambda v: format_money(v))
                df_tabla_caja["net_transfer_flow_fmt"] = df_tabla_caja["net_transfer_flow"].apply(lambda v: format_money(v, with_sign=True))
                df_tabla_caja["prize_flow_fmt"] = df_tabla_caja["prize_flow"].apply(lambda v: format_money(v, with_sign=True))

                st.dataframe(
                    df_tabla_caja[
                        ["position", "team_name", "manager_name", "points", "team_value_fmt", "cash_estimate_fmt", "net_transfer_flow_fmt", "prize_flow_fmt", "movements_count"]
                    ].sort_values("position"),
                    column_config={
                        "position": st.column_config.NumberColumn("Posición", format="%d"),
                        "team_name": st.column_config.TextColumn("Equipo"),
                        "manager_name": st.column_config.TextColumn("Mánager"),
                        "points": st.column_config.NumberColumn("Puntos"),
                        "team_value_fmt": st.column_config.TextColumn("Valor Plantilla"),
                        "cash_estimate_fmt": st.column_config.TextColumn("Caja Estimada"),
                        "net_transfer_flow_fmt": st.column_config.TextColumn("Flujo Fichajes"),
                        "prize_flow_fmt": st.column_config.TextColumn("Premios"),
                        "movements_count": st.column_config.NumberColumn("Movs"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

        if not df_movements.empty:
            st.markdown("#### 🔄 Últimos Movimientos y Actividad de la Liga")
            df_movements_display = df_movements.copy()
            df_movements_display["amount_fmt"] = df_movements_display["amount"].apply(lambda v: format_money(v))

            cols_mov = ["movement_date_str", "activity_desc", "player_name", "manager_name", "amount_fmt"]
            st.dataframe(
                df_movements_display[cols_mov].dropna(subset=["activity_desc"]),
                column_config={
                    "movement_date_str": st.column_config.TextColumn("Fecha"),
                    "activity_desc": st.column_config.TextColumn("Tipo de Actividad"),
                    "player_name": st.column_config.TextColumn("Jugador"),
                    "manager_name": st.column_config.TextColumn("Mánager"),
                    "amount_fmt": st.column_config.TextColumn("Importe"),
                },
                use_container_width=True,
                hide_index=True,
                height=400,
            )


if __name__ == "__main__":
    main()
