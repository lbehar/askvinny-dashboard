import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import plotly.express as px
from datetime import timedelta
import os

# ==============================================================
# 🌿 Page Setup & Styling
# ==============================================================

st.set_page_config(page_title="AskVinny — Weekly Agent Performance", page_icon="🏡", layout="wide")

st.markdown("""
<style>
.block-container {padding: 2rem 3rem 3rem 3rem;}
h2, h3 {margin-top: 2.2rem !important; margin-bottom: 1rem !important;}
div[data-testid="metric-container"] {margin-bottom: 20px;}
div[data-testid="stMetricValue"] {color: #00B140; font-weight: 700;}
body {background-color: #F9FBFA;}
div.stButton > button {
    background-color: transparent;
    border: none;
    color: #00B140;
    font-weight: 600;
    font-size: 1rem;
    padding: 0;
}
div.stButton > button:hover {
    color: #008a33;
    text-decoration: underline;
}
</style>
""", unsafe_allow_html=True)

st.title("🏡 AskVinny — Weekly Agent Performance")
st.caption("Analyse agent outcomes week-by-week to identify top performers and conversion results.")

# ==============================================================
# 🧩 Database Connection
# ==============================================================

db_url = st.secrets.get(
    "DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://placeholder@localhost:5432/neondb")
)
engine = create_engine(db_url)

# ==============================================================
# 🧮 Load Weekly Aggregated Data
# ==============================================================

@st.cache_data(ttl=3600)
def load_weekly_data():
    query = """
    WITH cleaned_viewings AS (
      SELECT "personId","Agent",TO_DATE("Date",'DD/MM/YYYY') AS viewing_date
      FROM viewings WHERE "personId" IS NOT NULL
    ),
    weekly AS (
      SELECT v."Agent" AS agent,
             DATE_TRUNC('week',v.viewing_date)::date AS week_start,
             COUNT(DISTINCT v."personId") AS total_viewings,
             COUNT(DISTINCT CASE WHEN p."Applied" IS NOT NULL THEN v."personId" END) AS applications,
             COUNT(DISTINCT CASE WHEN p."Status"='Current' THEN v."personId" END) AS tenants
      FROM cleaned_viewings v
      LEFT JOIN prospects p ON v."personId"=p."personId"
      GROUP BY 1,2
    )
    SELECT agent,
           week_start,
           week_start+INTERVAL '6 days' AS week_end,
           total_viewings, applications, tenants,
           ROUND(applications::NUMERIC/NULLIF(total_viewings,0)*100,1) AS view_to_app_rate,
           ROUND(tenants::NUMERIC/NULLIF(applications,0)*100,1) AS app_to_tenant_rate,
           ROUND(tenants::NUMERIC/NULLIF(total_viewings,0)*100,1) AS total_conversion_rate
    FROM weekly ORDER BY week_start,agent;
    """
    return pd.read_sql(query, engine)

df = load_weekly_data()

# ==============================================================
# 📅 Week Selection — Simplified UI
# ==============================================================

valid_weeks = pd.to_datetime(sorted(df["week_start"].unique())).tz_localize(None)
current_index = len(valid_weeks) - 1  # start at most recent week

if "selected_index" not in st.session_state:
    st.session_state.selected_index = current_index

selected_week = valid_weeks[st.session_state.selected_index]

# --- Jump to a specific date ---
with st.expander("📅 Jump to a specific date"):
    manual_date = st.date_input("Pick a date:", value=selected_week.to_pydatetime())
    manual_date = pd.to_datetime(manual_date)
    snap_week = manual_date - pd.to_timedelta(manual_date.weekday(), unit="d")

    # Snap to nearest valid dataset week
    nearest_week = valid_weeks[(abs(valid_weeks - snap_week)).argmin()]
    st.caption(f"Snapped to reporting week starting {nearest_week.strftime('%d %b %Y')}")

    selected_week = nearest_week
    st.session_state.selected_index = valid_weeks.tolist().index(nearest_week)

# ==============================================================
# ✅ Week Filter (Display + Data Sync)
# ==============================================================

df["week_start"] = pd.to_datetime(df["week_start"]).dt.tz_localize(None).dt.normalize()
selected_week = pd.to_datetime(selected_week).tz_localize(None).normalize()
week_df = df[df["week_start"] == selected_week]

if not week_df.empty:
    start_of_week = week_df["week_start"].iloc[0]
else:
    start_of_week = selected_week
end_of_week = start_of_week + timedelta(days=6)

week_label = f"{start_of_week.strftime('%d %b %Y')} – {end_of_week.strftime('%d %b %Y')}"
st.markdown(f"### Results for week of **{week_label}**")

if week_df.empty:
    st.warning(f"No data available for the week starting {selected_week.strftime('%d %b %Y')}.")
    st.stop()

# ==============================================================
# 💡 Weekly Highlights (Simplified – no runner-up)
# ==============================================================

top_row = week_df.loc[week_df["total_conversion_rate"].idxmax()]
top_agent = top_row["agent"]
top_rate = round(top_row["total_conversion_rate"], 1)
avg_rate = round(week_df["total_conversion_rate"].mean(), 1)

col1, col2 = st.columns(2)
with col1:
    st.metric("🏆 Top Agent", top_agent)
with col2:
    st.metric("Conversion Rate", f"{top_rate}%")

st.caption(f"Average conversion rate this week: **{avg_rate}%**")
# ==============================================================
# 📊 Weekly Bar Chart
# ==============================================================

melted = week_df.melt(
    id_vars=["agent"],
    value_vars=["total_viewings", "tenants"],
    var_name="Metric",
    value_name="Count"
).replace({"total_viewings": "Viewings", "tenants": "Tenants"})

fig = px.bar(
    melted, x="agent", y="Count", color="Metric", barmode="group",
    color_discrete_map={"Viewings": "#C9F5C2", "Tenants": "#00B140"},
    title=f"Viewings vs Tenants — Week of {week_label}",
    labels={"agent": "Agent", "Count": "Count"}
)
fig.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    height=450, margin=dict(t=60, b=40, l=40, r=40)
)
st.plotly_chart(fig, use_container_width=True)

# ==============================================================
# 📋 Weekly Data Table (with intermediate conversion column)
# ==============================================================

display_df = week_df.copy()

# Calculate intermediate conversion step
display_df["View→App (%)"] = round(
    (display_df["applications"] / display_df["total_viewings"] * 100)
    .replace([float("inf"), None], 0)
    .fillna(0),
    1
)

# Rename and reorder columns for clarity
display_df = display_df.rename(columns={
    "agent": "Agent",
    "total_viewings": "Viewings",
    "applications": "Applications",
    "tenants": "Tenants",
    "total_conversion_rate": "View→Tenant (%)"
})[
    ["Agent", "Viewings", "Applications", "Tenants", "View→App (%)", "View→Tenant (%)"]
]

st.dataframe(display_df, use_container_width=True)


st.caption(
    f"Dataset covers {df['week_start'].nunique()} total weeks "
    f"from {df['week_start'].min().strftime('%d %b %Y')} "
    f"to {df['week_start'].max().strftime('%d %b %Y')}."
)
