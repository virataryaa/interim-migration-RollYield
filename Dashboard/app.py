"""
Roll Yield Monitor — All Commodities
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Roll Yield Monitor", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
  [data-testid="stAppViewContainer"],[data-testid="stMain"],.main{background:#fafafa!important;color:#1d1d1f!important}
  [data-testid="stHeader"]{background:transparent!important}
  .block-container{padding-top:2rem!important;padding-bottom:1.5rem;max-width:1500px}
  hr{border:none!important;border-top:1px solid #e8e8ed!important;margin:.4rem 0!important}
  [data-testid="stRadio"] label,[data-testid="stRadio"] label p{color:#1d1d1f!important}
  [data-testid="stExpander"]{border:1px solid #e8e8ed!important;border-radius:8px!important;background:#fff!important}
  [data-testid="stSidebar"]{background:#f5f5f7!important;border-right:1px solid #e8e8ed!important}
  [data-testid="stSidebar"] *{color:#1d1d1f!important}
  [data-testid="stSidebar"] .block-container{padding-top:1.5rem!important}
  h1,h2,h3{color:#1d1d1f!important}
  html,body,[class*="css"]{color:#1d1d1f!important}
</style>""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
NAVY  = "#0a2463"
BLACK = "#1d1d1f"
_BASE = Path(__file__).parent.parent / "Database"

# lot_mult / rolls_yr are only read by the BMF tab now that the Roll Cost tab
# is gone; kept for the other entries so the config stays uniform and a future
# per-commodity cost view doesn't have to re-derive them.
COMM_CONFIG = {
    "KC":  {"name": "Arabica",      "color": "#0a2463", "lot_mult": 375,  "rolls_yr": 5},
    "RC":  {"name": "Robusta",      "color": "#8b1a00", "lot_mult": 10,   "rolls_yr": 5},
    "CC":  {"name": "NYC Cocoa",    "color": "#e8a020", "lot_mult": 10,   "rolls_yr": 5},
    "LCC": {"name": "LDN Cocoa",    "color": "#4a7fb5", "lot_mult": 10,   "rolls_yr": 5},
    "SB":  {"name": "Sugar",        "color": "#1a6b1a", "lot_mult": 1120, "rolls_yr": 4},
    "CT":  {"name": "Cotton",       "color": "#7b2d8b", "lot_mult": 500,  "rolls_yr": 5},
    "W":   {"name": "White Sugar",  "color": "#c0392b", "lot_mult": 50,   "rolls_yr": 6},
    "ZC":  {"name": "Corn",         "color": "#f39c12", "lot_mult": 50,   "rolls_yr": 5},
    "ZW":  {"name": "Wheat",        "color": "#d35400", "lot_mult": 50,   "rolls_yr": 5},
    "KE":  {"name": "KC Wheat",     "color": "#795548", "lot_mult": 50,   "rolls_yr": 5},
    "JO":  {"name": "Orange Juice", "color": "#e67e22", "lot_mult": 150,  "rolls_yr": 5},
    # B3/BM&F Arabica (ICF): quoted USD per 60kg bag, 100 bags per lot,
    # H/K/N/U/Z like KC. Its c2-c1 spread is USD/bag, so the BMF tab shows a
    # $/Lot figure (lot_mult 100) to put it in comparable money.
    "BMF": {"name": "BMF Arabica",  "color": "#00897b", "lot_mult": 100,  "rolls_yr": 5},
    # carry point is c5 (~6m), not c7 (~1yr) - B3's curve is only liquid to ~c5
}

# BMF is quoted in USD/60kg-bag on a 6-month carry, not a 1yr one like the
# rest, so it gets its own tab and is excluded from the cross-commodity
# Roll Yield tab.
BMF    = "BMF"
COMMS  = [k for k in COMM_CONFIG if k != BMF]
NAMES  = {k: v["name"] for k, v in COMM_CONFIG.items()}
COLORS = {k: v["color"] for k, v in COMM_CONFIG.items()}
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

_D = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="-apple-system,Helvetica Neue,sans-serif", color=BLACK, size=10),
)

def lbl(text):
    return (f"<div style='background:{NAVY};padding:5px 13px;border-radius:5px;"
            f"margin-bottom:8px'><span style='font-size:.78rem;font-weight:500;"
            f"letter-spacing:.07em;text-transform:uppercase;color:#dde4f0'>{text}</span></div>")

# ── Demo data generator ───────────────────────────────────────────────────────
def _generate_demo():
    dates = pd.bdate_range("2020-01-01", pd.Timestamp.today())
    np.random.seed(42)
    rows = []
    for comm, cfg in COMM_CONFIG.items():
        spot0   = {"KC": 150, "RC": 2000, "CC": 2500, "LCC": 1800,
                   "SB": 15,  "CT": 80,   "W": 400,   "ZC": 450,
                   "ZW": 550, "KE": 570,  "JO": 130, "BMF": 390}[comm]
        spot    = spot0 * np.exp(np.cumsum(np.random.normal(0, 0.008, len(dates))))
        base_ry = np.random.uniform(0.03, 0.15)
        ry      = base_ry + np.random.normal(0, 0.02, len(dates))
        ry      = pd.Series(ry).rolling(20).mean().fillna(base_ry).values
        yr1     = spot / (1 + ry)
        for i, d in enumerate(dates):
            spread = yr1[i] - spot[i]
            curve  = [spot[i] + spread * (j / 7) for j in range(8)]
            rows.append({
                "Date": d, "Commodity": comm,
                "Spot": round(spot[i], 2), "OneYr": round(yr1[i], 2),
                "Roll_Yield_1yr": round(ry[i], 6),
                **{f"c{j+1}": round(curve[j], 2) for j in range(8)},
            })
    return pd.DataFrame(rows)

# ── Load data ─────────────────────────────────────────────────────────────────
def _stamp(name: str):
    """mtime of a Database file, or None if absent. Passed into the cached
    loaders purely as part of their cache key: the daily ingest rewrites these
    parquets in place, and without the mtime in the key Streamlit keeps serving
    the previous load until the ttl lapses or the process restarts.

    The receiving param must NOT be underscore-prefixed — Streamlit excludes
    those from hashing, which would silently defeat the point."""
    pq = _BASE / name
    return pq.stat().st_mtime if pq.exists() else None


@st.cache_data(ttl=3600)
def load_data(stamp):
    pq = _BASE / "roll_yield_data.parquet"
    if pq.exists():
        df = pd.read_parquet(pq)
        df["Date"] = pd.to_datetime(df["Date"])
        return df, False
    return _generate_demo(), True


@st.cache_data(ttl=3600)
def load_fx(stamp):
    """USD/BRL for the diff tab. Optional — returns None if the ingest hasn't
    written it, and the tab hides its BRL panels rather than erroring."""
    pq = _BASE / "fx_brl.parquet"
    if not pq.exists():
        return None
    fx = pd.read_parquet(pq)
    fx["Date"] = pd.to_datetime(fx["Date"])
    return fx.set_index("Date")[["USDBRL"]].astype("float64")


df, is_demo = load_data(_stamp("roll_yield_data.parquet"))

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    "<h2 style='font-family:\"Playfair Display\",Georgia,serif;color:#0a2463;"
    "font-weight:400;letter-spacing:-.01em;margin-bottom:2px'>Roll Yield Monitor</h2>",
    unsafe_allow_html=True,
)
if is_demo:
    st.info("Demo mode — synthetic data. Run roll_yield_ingest.py to load live data.")
st.markdown("<hr>", unsafe_allow_html=True)

# ── Shared date filter ────────────────────────────────────────────────────────
min_d         = df["Date"].min().date()
max_d         = df["Date"].max().date()
default_start = (df["Date"].max() - pd.DateOffset(years=3)).date()

with st.sidebar:
    st.markdown(
        "<div style='font-family:\"Playfair Display\",Georgia,serif;color:#0a2463;"
        "font-size:1.15rem;margin-bottom:.6rem'>Controls</div>",
        unsafe_allow_html=True,
    )
    sel_comms = st.multiselect(
        "Commodities",
        options=COMMS,
        default=["KC", "RC", "CC"],
        format_func=lambda x: f"{x} — {NAMES[x]}",
        key="ms_comms",
        help="Roll Yield tab only. BMF has its own tab — different units and carry tenor.",
    )
    date_range = st.slider(
        "Date range", min_value=min_d, max_value=max_d,
        value=(default_start, max_d), key="sl_dates",
    )
    st.markdown("<hr>", unsafe_allow_html=True)
    st.caption(f"Data through {max_d.strftime('%d/%m/%Y')}")

start_d, end_d = date_range
df_fil = df[(df["Date"].dt.date >= start_d) & (df["Date"].dt.date <= end_d)]

# ── Tabs ──────────────────────────────────────────────────────────────────────
ry_tab, bmf_tab, diff_tab = st.tabs(["Roll Yield", "BMF Arabica", "KC vs BMF Diff"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ROLL YIELD (existing content unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
with ry_tab:

    # SECTION 1 — Roll Yield Line Chart
    st.markdown(lbl("1-Year Roll Yield (%) — Spot / 1yr − 1"), unsafe_allow_html=True)
    fig_line = go.Figure()
    for comm in sel_comms:
        s = df_fil[df_fil["Commodity"] == comm].sort_values("Date")
        fig_line.add_trace(go.Scatter(
            x=s["Date"], y=(s["Roll_Yield_1yr"] * 100).round(2),
            name=NAMES[comm], mode="lines",
            line=dict(color=COLORS[comm], width=1.8),
            hovertemplate=f"<b>{NAMES[comm]}</b>  %{{x|%d %b %Y}}  %{{y:.1f}}%<extra></extra>",
        ))
    fig_line.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
    fig_line.update_layout(
        height=370,
        xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                   ticksuffix="%", title="Roll Yield (%)"),
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=8, color=BLACK), bgcolor="rgba(255,255,255,0.7)"),
        margin=dict(t=10, b=10, l=4, r=4), **_D,
    )
    st.plotly_chart(fig_line, use_container_width=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    # SECTION 2 — Ranking + Percentile
    col_rank, col_pct = st.columns(2)
    latest_date = df_fil["Date"].max()
    df_latest   = df_fil[df_fil["Date"] == latest_date].set_index("Commodity")

    with col_rank:
        st.markdown(lbl(f"Roll Yield Ranking · {latest_date.strftime('%d/%m/%Y')}"), unsafe_allow_html=True)
        rank_rows = []
        for comm in COMMS:
            if comm in df_latest.index:
                ry = df_latest.loc[comm, "Roll_Yield_1yr"] * 100
                rank_rows.append({"Rank": 0, "Commodity": NAMES[comm], "Roll Yield (1yr)": f"{ry:+.1f}%", "_ry": ry})
        rank_df = pd.DataFrame(rank_rows).sort_values("_ry", ascending=False).reset_index(drop=True)
        rank_df["Rank"] = rank_df.index + 1
        fig_rank = go.Figure(go.Table(
            columnwidth=[30, 100, 80],
            header=dict(
                values=["Rank", "Commodity", "Roll Yield (1yr)"],
                fill_color=NAVY, font=dict(color="white", size=10),
                align="center", height=28,
            ),
            cells=dict(
                values=[rank_df["Rank"], rank_df["Commodity"], rank_df["Roll Yield (1yr)"]],
                fill_color=[["white" if i % 2 == 0 else "#f5f5f7" for i in range(len(rank_df))]],
                font=dict(color=[
                    ["white"]*len(rank_df),
                    [BLACK]*len(rank_df),
                    [("#1a6b1a" if r > 0 else "#8b0000") for r in rank_df["_ry"]],
                ], size=10),
                align="center", height=24,
            ),
        ))
        fig_rank.update_layout(height=340, margin=dict(t=0, b=0, l=0, r=0), **_D)
        st.plotly_chart(fig_rank, use_container_width=True)

    with col_pct:
        st.markdown(lbl("Roll Yield Percentile vs Full History"), unsafe_allow_html=True)
        pct_rows = []
        for comm in COMMS:
            hist = df[df["Commodity"] == comm]["Roll_Yield_1yr"].dropna()
            if hist.empty:
                continue
            cur = df_latest.loc[comm, "Roll_Yield_1yr"] if comm in df_latest.index else np.nan
            if np.isnan(cur):
                continue
            pct = float((hist < cur).mean() * 100)
            pct_rows.append({"Commodity": NAMES[comm], "Percentile": round(pct, 1), "color": COLORS[comm]})
        pct_df = pd.DataFrame(pct_rows).sort_values("Percentile", ascending=True)
        fig_pct = go.Figure(go.Bar(
            x=pct_df["Percentile"], y=pct_df["Commodity"],
            orientation="h", marker_color=pct_df["color"],
            text=pct_df["Percentile"].map(lambda x: f"{x:.0f}th"),
            textposition="outside", textfont=dict(size=9, color=BLACK),
        ))
        fig_pct.add_vline(x=50, line_dash="dot", line_color="#aaaaaa", line_width=1)
        fig_pct.add_vline(x=80, line_dash="dot", line_color="#e07b39", line_width=1)
        fig_pct.update_layout(
            height=340,
            xaxis=dict(range=[0, 115], showgrid=False, tickfont=dict(size=9, color=BLACK), ticksuffix="%"),
            yaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            margin=dict(t=0, b=0, l=4, r=60), **_D,
        )
        st.plotly_chart(fig_pct, use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # SECTION 3 — Forward Curves
    curve_comm  = st.selectbox("Commodity for curves", COMMS, format_func=lambda x: f"{x} — {NAMES[x]}", key="curve_comm")
    curve_color = COLORS[curve_comm]
    curve_cols  = [f"c{i}" for i in range(1, 9)]
    curve_labels= [f"c{i}" for i in range(1, 9)]
    df_comm     = df_fil[df_fil["Commodity"] == curve_comm].sort_values("Date")
    all_dates_sorted = df_comm["Date"].drop_duplicates().sort_values()
    latest_4d   = all_dates_sorted.iloc[-4:].tolist() if len(all_dates_sorted) >= 4 else all_dates_sorted.tolist()
    weekly_idx  = list(range(-1, -len(all_dates_sorted), -5))[:4]
    latest_4w   = [all_dates_sorted.iloc[i] for i in sorted(weekly_idx)]
    day_colors  = ["#1d1d1f", "#c0392b", "#82c982", "#aaaaaa"]

    st.markdown(lbl(f"Forward Curves · {NAMES[curve_comm]}"), unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns(3)

    def _curve_fig(dates, colors, title):
        fig = go.Figure()
        for d, col in zip(dates, colors):
            row = df_comm[df_comm["Date"] == d]
            if row.empty:
                continue
            y = [row.iloc[0][c] for c in curve_cols]
            fig.add_trace(go.Scatter(
                x=curve_labels, y=y, mode="lines+markers",
                name=d.strftime("%d/%m/%Y"),
                line=dict(color=col, width=2), marker=dict(size=5),
                hovertemplate="%{x}  %{y:.2f}<extra></extra>",
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=11, color=BLACK), x=0.5, xanchor="center"),
            height=320,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK)),
            legend=dict(font=dict(size=8, color=BLACK), bgcolor="rgba(255,255,255,0.7)"),
            margin=dict(t=35, b=10, l=4, r=4), **_D,
        )
        return fig

    with fc1:
        latest_row = df_comm[df_comm["Date"] == all_dates_sorted.iloc[-1]]
        y_latest   = [latest_row.iloc[0][c] for c in curve_cols]
        fig_latest = go.Figure(go.Scatter(
            x=curve_labels, y=y_latest, mode="lines+markers",
            line=dict(color=curve_color, width=2.5), marker=dict(size=6),
            hovertemplate="%{x}  %{y:.2f}<extra></extra>",
        ))
        fig_latest.update_layout(
            title=dict(text=f"Latest · {all_dates_sorted.iloc[-1].strftime('%d/%m/%Y')}",
                       font=dict(size=11, color=BLACK), x=0.5, xanchor="center"),
            height=320,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK)),
            margin=dict(t=35, b=10, l=4, r=4), **_D,
        )
        st.plotly_chart(fig_latest, use_container_width=True)
    with fc2:
        st.plotly_chart(_curve_fig(latest_4d, day_colors, "Last 4 Days"), use_container_width=True)
    with fc3:
        st.plotly_chart(_curve_fig(latest_4w, day_colors, "Last 4 Weeks"), use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # SECTION 4 — Roll Yield Heatmap
    hm_comm = st.selectbox("Commodity for Heatmap", COMMS, format_func=lambda x: f"{x} — {NAMES[x]}", key="hm_comm")
    st.markdown(lbl(f"Roll Yield Heatmap · {NAMES[hm_comm]} · Monthly Avg"), unsafe_allow_html=True)
    hm_s = df_fil[df_fil["Commodity"] == hm_comm].copy()
    hm_s["Roll_Yield_1yr"] = pd.to_numeric(hm_s["Roll_Yield_1yr"], errors="coerce")
    hm_s["Year"]  = hm_s["Date"].dt.year
    hm_s["Month"] = hm_s["Date"].dt.month
    pivot = (
        hm_s.groupby(["Year", "Month"])["Roll_Yield_1yr"]
        .mean().reset_index()
        .pivot(index="Year", columns="Month", values="Roll_Yield_1yr")
    )
    if not pivot.empty:
        pivot.columns = [MONTHS[int(m) - 1] for m in pivot.columns]
        pivot = pivot.sort_index(ascending=False)
        z       = (pivot.to_numpy(dtype='float64', na_value=np.nan) * 100).round(2)
        years   = [str(y) for y in pivot.index]
        months  = list(pivot.columns)
        text_mat= [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in z]
        fig_hm  = go.Figure(go.Heatmap(
            z=z, x=months, y=years, text=text_mat, texttemplate="%{text}",
            textfont=dict(size=8, color=BLACK),
            colorscale=[[0.0,"#8b0000"],[0.4,"#f5c6cb"],[0.5,"#ffffff"],[0.6,"#d4edda"],[1.0,"#1a6b1a"]],
            zmid=0,
            colorbar=dict(title=dict(text="Roll Yield %", font=dict(size=9, color=BLACK)),
                          tickfont=dict(size=8, color=BLACK), ticksuffix="%", thickness=12, len=0.8),
            hoverongaps=False,
            hovertemplate="<b>%{y} · %{x}</b><br>Avg Roll Yield: %{z:.1f}%<extra></extra>",
        ))
        fig_hm.update_layout(
            height=max(300, len(years) * 28),
            xaxis=dict(side="top", tickfont=dict(size=9, color=BLACK), showgrid=False),
            yaxis=dict(tickfont=dict(size=9, color=BLACK), showgrid=False),
            margin=dict(t=40, b=10, l=60, r=10), **_D,
        )
        st.plotly_chart(fig_hm, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — BMF ARABICA (B3/BM&F, LSEG continuation root ICF)
# ═══════════════════════════════════════════════════════════════════════════════
with bmf_tab:

    b = df_fil[df_fil["Commodity"] == BMF].sort_values("Date").copy()

    if b.empty:
        st.warning("No BMF data in the selected date range.")
    else:
        b["roll_spread"] = b["c2"] - b["c1"]
        b_mult   = COMM_CONFIG[BMF]["lot_mult"]
        b_rolls  = COMM_CONFIG[BMF]["rolls_yr"]
        b_color  = COMM_CONFIG[BMF]["color"]
        last     = b.iloc[-1]

        st.caption(
            "B3/BM&F Arabica Coffee (ICF) — 100 bags x 60kg per lot, quoted USD per 60kg bag, "
            "H/K/N/U/Z months. Carry shown here is a **6-month** figure (c2 vs c5), not the "
            "1-year measure used on the other two tabs: B3's curve is only genuinely liquid "
            "out to about c5."
        )

        # ── KPI strip ─────────────────────────────────────────────────────────
        hist_all = df[df["Commodity"] == BMF]["Roll_Yield_1yr"].dropna()
        pctile   = float((hist_all < last["Roll_Yield_1yr"]).mean() * 100)
        ann_lot  = last["roll_spread"] * b_mult * b_rolls
        kpis = [
            ("Front (c1)",        f"{last['c1']:,.2f}",                    "USD / 60kg bag"),
            ("6m Carry",          f"{last['Roll_Yield_1yr'] * 100:+.1f}%", "c2 / c5 - 1"),
            ("Percentile",        f"{pctile:.0f}th",                       "vs full history"),
            ("Roll Spread c2-c1", f"{last['roll_spread']:+.2f}",           "USD / bag"),
            ("Roll Cost / Lot",   f"${last['roll_spread'] * b_mult:+,.0f}", f"annualised ${ann_lot:+,.0f}"),
        ]
        for col, (label, val, sub) in zip(st.columns(len(kpis)), kpis):
            with col:
                st.markdown(
                    "<div style='background:#fff;border:1px solid #e8e8ed;border-radius:8px;"
                    "padding:10px 14px'>"
                    "<div style='font-size:.62rem;letter-spacing:.07em;text-transform:uppercase;"
                    f"color:#8a8a8f'>{label}</div>"
                    f"<div style='font-size:1.35rem;font-weight:500;color:{NAVY};margin:2px 0'>{val}</div>"
                    f"<div style='font-size:.62rem;color:#8a8a8f'>{sub}</div></div>",
                    unsafe_allow_html=True,
                )
        st.markdown(
            "<div style='font-size:.68rem;color:#8a8a8f;margin-top:6px'>"
            f"as of {last['Date'].strftime('%d/%m/%Y')}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 1 — 6m carry over time ────────────────────────────────────
        st.markdown(lbl("BMF Arabica 6-Month Carry (%) — c2 / c5 − 1"), unsafe_allow_html=True)
        fig_b = go.Figure(go.Scatter(
            x=b["Date"], y=(b["Roll_Yield_1yr"] * 100).round(2),
            mode="lines", line=dict(color=b_color, width=1.8),
            hovertemplate="<b>BMF</b>  %{x|%d %b %Y}  %{y:.1f}%<extra></extra>",
        ))
        fig_b.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
        fig_b.update_layout(
            height=340,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                       ticksuffix="%", title="6m Carry (%)"),
            margin=dict(t=10, b=10, l=4, r=4), **_D,
        )
        st.plotly_chart(fig_b, use_container_width=True)
        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 2 — Forward curve + seasonal roll spread ──────────────────
        bc1, bc2 = st.columns(2)
        b_dates  = b["Date"].drop_duplicates().sort_values()

        with bc1:
            st.markdown(lbl("Forward Curve · c1−c5 · Latest vs Last 4 Weeks"), unsafe_allow_html=True)
            # c6-c8 deliberately omitted - too illiquid on B3 to plot honestly.
            cols_b   = [f"c{i}" for i in range(1, 6)]
            wk_idx   = list(range(-1, -len(b_dates), -5))[:4]
            wk_dates = [b_dates.iloc[i] for i in sorted(wk_idx)]
            fig_bc   = go.Figure()
            for d, col in zip(wk_dates, ["#aaaaaa", "#82c982", "#c0392b", "#1d1d1f"]):
                row = b[b["Date"] == d]
                if row.empty:
                    continue
                is_latest = d == b_dates.iloc[-1]
                # c4 in particular can sit unprinted for weeks; pd.NA breaks
                # plotly, so coerce to float/None and let the line bridge it.
                y_vals = [None if pd.isna(row.iloc[0][c]) else float(row.iloc[0][c])
                          for c in cols_b]
                fig_bc.add_trace(go.Scatter(
                    x=cols_b, y=y_vals, connectgaps=True,
                    mode="lines+markers", name=d.strftime("%d/%m/%Y"),
                    line=dict(color=b_color if is_latest else col, width=2.5 if is_latest else 1.6),
                    marker=dict(size=6 if is_latest else 4),
                    hovertemplate="%{x}  %{y:.2f}<extra></extra>",
                ))
            fig_bc.update_layout(
                height=330,
                xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
                yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                           title="USD / bag"),
                legend=dict(font=dict(size=8, color=BLACK), bgcolor="rgba(255,255,255,0.7)"),
                margin=dict(t=10, b=10, l=4, r=4), **_D,
            )
            st.plotly_chart(fig_bc, use_container_width=True)

        with bc2:
            st.markdown(lbl("Seasonal Roll Spread (c2−c1) — Avg by Month"), unsafe_allow_html=True)
            bs = b.copy()
            bs["Month"] = bs["Date"].dt.month
            bs_avg = bs.groupby("Month")["roll_spread"].mean().reindex(range(1, 13))
            fig_bs = go.Figure(go.Bar(
                x=MONTHS, y=bs_avg.values.round(2),
                marker_color=["#8b0000" if v > 0 else "#1a6b1a" for v in bs_avg.fillna(0)],
                text=[f"{v:.2f}" if not np.isnan(v) else "" for v in bs_avg.values],
                textposition="outside", textfont=dict(size=8, color=BLACK),
                hovertemplate="<b>%{x}</b><br>Avg spread: %{y:.2f} USD/bag<extra></extra>",
            ))
            fig_bs.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
            fig_bs.update_layout(
                height=330,
                xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
                yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                           title="Avg c2−c1 (USD/bag)"),
                margin=dict(t=10, b=10, l=4, r=4), **_D,
            )
            st.plotly_chart(fig_bs, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 3 — Carry heatmap ─────────────────────────────────────────
        st.markdown(lbl("BMF 6-Month Carry Heatmap · Monthly Avg"), unsafe_allow_html=True)
        bh = b.copy()
        bh["Year"], bh["Month"] = bh["Date"].dt.year, bh["Date"].dt.month
        bp = (
            bh.groupby(["Year", "Month"])["Roll_Yield_1yr"]
            .mean().reset_index()
            .pivot(index="Year", columns="Month", values="Roll_Yield_1yr")
        )
        if not bp.empty:
            bp.columns = [MONTHS[int(m) - 1] for m in bp.columns]
            bp = bp.sort_index(ascending=False)
            zb = (bp.to_numpy(dtype="float64", na_value=np.nan) * 100).round(2)
            fig_bh = go.Figure(go.Heatmap(
                z=zb, x=list(bp.columns), y=[str(y) for y in bp.index],
                text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in zb],
                texttemplate="%{text}", textfont=dict(size=8, color=BLACK),
                colorscale=[[0.0,"#8b0000"],[0.4,"#f5c6cb"],[0.5,"#ffffff"],[0.6,"#d4edda"],[1.0,"#1a6b1a"]],
                zmid=0,
                colorbar=dict(title=dict(text="6m Carry %", font=dict(size=9, color=BLACK)),
                              tickfont=dict(size=8, color=BLACK), ticksuffix="%", thickness=12, len=0.8),
                hoverongaps=False,
                hovertemplate="<b>%{y} · %{x}</b><br>Avg 6m Carry: %{z:.1f}%<extra></extra>",
            ))
            fig_bh.update_layout(
                height=max(300, len(bp.index) * 28),
                xaxis=dict(side="top", tickfont=dict(size=9, color=BLACK), showgrid=False),
                yaxis=dict(tickfont=dict(size=9, color=BLACK), showgrid=False),
                margin=dict(t=40, b=10, l=60, r=10), **_D,
            )
            st.plotly_chart(fig_bh, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — KC vs BMF DIFF
# ═══════════════════════════════════════════════════════════════════════════════
# The two contracts are the same physical commodity on the same five months, so
# once BMF is converted to US cents/lb the difference is readable as a Brazil
# differential proxy (origin diff + internal logistics + BRL + financing) rather
# than as an arb — cross-delivery between B3 and ICE is not practical.
# Front month only, deliberately: B3 is too thin past ~c3 for the deferred legs
# to carry information rather than staleness.
with diff_tab:

    LB_PER_BAG = 60 / 0.45359237     # 60kg bag -> lbs (132.2774)

    kc_ = df_fil[df_fil["Commodity"] == "KC"].set_index("Date")[["c1", "c2"]]
    bm_ = df_fil[df_fil["Commodity"] == BMF].set_index("Date")[["c1", "c2"]]
    dfd = kc_.join(bm_, how="inner", lsuffix="_KC", rsuffix="_BMF").astype("float64")
    # BMF: USD per 60kg bag -> US cents per lb, putting both legs on KC's units.
    dfd["BMF"]  = dfd["c2_BMF"] * 100.0 / LB_PER_BAG
    dfd["KC"]   = dfd["c2_KC"]
    dfd["Diff"] = dfd["KC"] - dfd["BMF"]
    dfd = dfd.dropna(subset=["Diff"]).sort_index()

    if dfd.empty:
        st.warning("No overlapping KC / BMF data in the selected date range.")
    else:
        st.caption(
            "BMF converted to KC's units: USD/60kg bag ÷ 132.2774 lb/bag × 100 "
            "= US cents/lb. Diff = KC c2 − BMF c2."
        )

        # ── SECTION 1 — Diff with mean / sd bands ─────────────────────────────
        st.markdown(lbl("KC − BMF Differential (US cents/lb) · 1yr Mean ±1 / ±2 sd"), unsafe_allow_html=True)
        roll_m  = dfd["Diff"].rolling(252, min_periods=60).mean()
        roll_s  = dfd["Diff"].rolling(252, min_periods=60).std()
        fig_d   = go.Figure()
        for mult, shade in ((2, "rgba(10,36,99,0.06)"), (1, "rgba(10,36,99,0.10)")):
            fig_d.add_trace(go.Scatter(x=dfd.index, y=roll_m + mult * roll_s, mode="lines",
                                       line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig_d.add_trace(go.Scatter(x=dfd.index, y=roll_m - mult * roll_s, mode="lines",
                                       line=dict(width=0), fill="tonexty", fillcolor=shade,
                                       name=f"±{mult} sd", hoverinfo="skip"))
        fig_d.add_trace(go.Scatter(
            x=dfd.index, y=roll_m, mode="lines", name="1yr mean",
            line=dict(color="#8a8a8f", width=1, dash="dot"), hoverinfo="skip"))
        fig_d.add_trace(go.Scatter(
            x=dfd.index, y=dfd["Diff"].round(2), mode="lines", name="KC − BMF",
            line=dict(color=NAVY, width=1.8),
            hovertemplate="%{x|%d %b %Y}  %{y:.1f} c/lb<extra></extra>"))
        fig_d.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
        fig_d.update_layout(
            height=380,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                       title="KC − BMF (US c/lb)"),
            legend=dict(orientation="h", y=1.02, x=0, font=dict(size=8, color=BLACK),
                        bgcolor="rgba(255,255,255,0.7)"),
            margin=dict(t=10, b=10, l=4, r=4), **_D,
        )
        st.plotly_chart(fig_d, use_container_width=True)
        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 2 — Both legs ─────────────────────────────────────────────
        st.markdown(lbl("Both Legs · Front Month · US cents/lb"), unsafe_allow_html=True)
        fig_lg = go.Figure()
        for nm, col in (("KC", COLORS["KC"]), ("BMF", COMM_CONFIG[BMF]["color"])):
            fig_lg.add_trace(go.Scatter(
                x=dfd.index, y=dfd[nm].round(2), mode="lines", name=nm,
                line=dict(color=col, width=1.6),
                hovertemplate=f"<b>{nm}</b>  %{{x|%d %b %Y}}  %{{y:.1f}}<extra></extra>"))
        fig_lg.update_layout(
            height=330,
            xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9, color=BLACK),
                       title="US c/lb"),
            legend=dict(orientation="h", y=1.02, x=0, font=dict(size=8, color=BLACK),
                        bgcolor="rgba(255,255,255,0.7)"),
            margin=dict(t=10, b=10, l=4, r=4), **_D,
        )
        st.plotly_chart(fig_lg, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 3 — BRL (optional: only if the FX parquet exists) ─────────
        fx = load_fx(_stamp("fx_brl.parquet"))
        if fx is None:
            st.caption("USD/BRL panel hidden — Database/fx_brl.parquet not found. "
                       "Run Code/ingest_lseg.py to populate it.")
        else:
            dfx = dfd[["Diff"]].join(fx, how="inner").dropna()
            if len(dfx) < 60:
                st.caption("Not enough overlapping USD/BRL data in this range for the BRL panels.")
            else:
                fc1, fc2 = st.columns(2)

                with fc1:
                    st.markdown(lbl("Diff vs USD/BRL — Dual Axis"), unsafe_allow_html=True)
                    fig_fx = go.Figure()
                    fig_fx.add_trace(go.Scatter(
                        x=dfx.index, y=dfx["Diff"].round(2), name="KC − BMF",
                        mode="lines", line=dict(color=NAVY, width=1.6),
                        hovertemplate="%{x|%d %b %Y}  %{y:.1f} c/lb<extra></extra>"))
                    fig_fx.add_trace(go.Scatter(
                        x=dfx.index, y=dfx["USDBRL"].round(3), name="USD/BRL",
                        mode="lines", line=dict(color="#1a6b1a", width=1.4), yaxis="y2",
                        hovertemplate="%{x|%d %b %Y}  %{y:.3f}<extra></extra>"))
                    fig_fx.update_layout(
                        height=330,
                        xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
                        yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                                   tickfont=dict(size=9, color=NAVY), title="KC − BMF (c/lb)"),
                        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                    tickfont=dict(size=9, color="#1a6b1a"), title="USD/BRL"),
                        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=8, color=BLACK),
                                    bgcolor="rgba(255,255,255,0.7)"),
                        margin=dict(t=10, b=10, l=4, r=4), **_D,
                    )
                    st.plotly_chart(fig_fx, use_container_width=True)

                with fc2:
                    st.markdown(lbl("Rolling 120d Correlation — Δ Diff vs Δ USD/BRL"), unsafe_allow_html=True)
                    # Correlate daily *changes*, not levels: both series are highly
                    # persistent, so a level correlation would mostly report trend.
                    ch = dfx.diff().dropna()
                    rc = ch["Diff"].rolling(120).corr(ch["USDBRL"]).dropna()
                    full_r = ch["Diff"].corr(ch["USDBRL"])
                    fig_rc = go.Figure(go.Scatter(
                        x=rc.index, y=rc.round(3), mode="lines",
                        line=dict(color="#1a6b1a", width=1.6),
                        hovertemplate="%{x|%d %b %Y}  r = %{y:.2f}<extra></extra>"))
                    fig_rc.add_hline(y=0, line_dash="dot", line_color="#aaaaaa", line_width=1)
                    fig_rc.add_hline(y=full_r, line_dash="dash", line_color="#8a8a8f", line_width=1,
                                     annotation_text=f"full-period r = {full_r:.2f}",
                                     annotation_font=dict(size=8, color="#8a8a8f"))
                    fig_rc.update_layout(
                        height=330,
                        xaxis=dict(showgrid=False, tickfont=dict(size=9, color=BLACK)),
                        yaxis=dict(range=[-1, 1], showgrid=True, gridcolor="#f0f0f0",
                                   tickfont=dict(size=9, color=BLACK), title="corr"),
                        margin=dict(t=10, b=10, l=4, r=4), **_D,
                    )
                    st.plotly_chart(fig_rc, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── SECTION 4 — Diff heatmap ──────────────────────────────────────────
        st.markdown(lbl("KC − BMF Differential Heatmap · Monthly Avg (US cents/lb)"), unsafe_allow_html=True)
        dh = dfd.copy()
        dh["Year"], dh["Month"] = dh.index.year, dh.index.month
        dp = (
            dh.groupby(["Year", "Month"])["Diff"].mean().reset_index()
            .pivot(index="Year", columns="Month", values="Diff")
        )
        if not dp.empty:
            dp.columns = [MONTHS[int(m) - 1] for m in dp.columns]
            dp = dp.sort_index(ascending=False)
            zd = dp.to_numpy(dtype="float64", na_value=np.nan).round(1)
            fig_dh = go.Figure(go.Heatmap(
                z=zd, x=list(dp.columns), y=[str(y) for y in dp.index],
                text=[[f"{v:.1f}" if not np.isnan(v) else "" for v in row] for row in zd],
                texttemplate="%{text}", textfont=dict(size=8, color=BLACK),
                colorscale=[[0.0, "#ffffff"], [0.5, "#9fb3d9"], [1.0, "#0a2463"]],
                colorbar=dict(title=dict(text="c/lb", font=dict(size=9, color=BLACK)),
                              tickfont=dict(size=8, color=BLACK), thickness=12, len=0.8),
                hoverongaps=False,
                hovertemplate="<b>%{y} · %{x}</b><br>Avg diff: %{z:.1f} c/lb<extra></extra>",
            ))
            fig_dh.update_layout(
                height=max(300, len(dp.index) * 28),
                xaxis=dict(side="top", tickfont=dict(size=9, color=BLACK), showgrid=False),
                yaxis=dict(tickfont=dict(size=9, color=BLACK), showgrid=False),
                margin=dict(t=40, b=10, l=60, r=10), **_D,
            )
            st.plotly_chart(fig_dh, use_container_width=True)
