import streamlit as st
import pandas as pd
import plotly.express as px
import re

st.set_page_config(page_title="QuantData Order Type Buckets", page_icon="📊", layout="wide")

# ---------- Theme ----------
st.markdown("""
<style>
.stApp { background: #0b0f17; color: #e8edf5; }
[data-testid="stSidebar"] { background: #111722; border-right: 1px solid #263244; }
div[data-testid="metric-container"] { background:#121a26; border:1px solid #263244; padding:14px; border-radius:10px; }
div[data-testid="stMetricValue"] { color:#eaf2ff; }
.block-container { padding-top: 1.2rem; }
h1,h2,h3 { color:#eaf2ff; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Options Flow — Order Type Buckets")
st.caption("Expiration-based flow analytics | QuantData CSV")

uploaded = st.file_uploader("Upload QuantData Options Order Flow CSV", type=["csv"])
if not uploaded:
    st.info("Upload your QuantData CSV to load the dashboard.")
    st.stop()

@st.cache_data(show_spinner="Reading and cleaning CSV…")
def load_data(file):
    d = pd.read_csv(file, low_memory=False)
    # Currency / numeric cleanup
    def num(s):
        return pd.to_numeric(
            s.astype(str).str.replace(r"[$,%]", "", regex=True)
             .str.replace(",", "", regex=False).str.strip(),
            errors="coerce"
        )
    for c in ["Premium Price","Size","Option Price","Ask Price","Bid Price",
               "Volume","Open Interest","Strike Price","Reference Price",
               "Days Until Expiration","Delta"]:
        if c in d.columns: d[c] = num(d[c])
    for c in ["Trade Time","Expiration Date"]:
        if c in d.columns: d[c] = pd.to_datetime(d[c], errors="coerce", utc=(c=="Trade Time"))
    for c in ["Ticker","Trade Type","Consolidation Type","Contract Type",
               "Is Opening Position","Is Golden Sweep","Side Code"]:
        if c in d.columns: d[c] = d[c].astype(str).str.strip().str.upper()
    return d

df = load_data(uploaded)

# Data definitions
# Sweeps/blocks are Consolidation Type. Open position is Is Opening Position.
if "Consolidation Type" not in df: df["Consolidation Type"] = "UNKNOWN"
if "Is Opening Position" not in df: df["Is Opening Position"] = "NO"
if "Trade Type" not in df: df["Trade Type"] = "UNKNOWN"

# ----- Sidebar controls -----
st.sidebar.header("Dashboard Filters")
tickers = sorted(df["Ticker"].dropna().astype(str).unique()) if "Ticker" in df else []
ticker_options = ["All"] + tickers
ticker = st.sidebar.selectbox("Ticker", ticker_options, index=0)

# Pinpoint underlying price (QuantData Reference Price)
st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Pinpoint Price")
pinpoint_enabled = st.sidebar.toggle("Enable pinpoint price filter", False)
pinpoint_price = None
pinpoint_tolerance = 0.0
if pinpoint_enabled:
    ref_values = pd.to_numeric(df.get("Reference Price", pd.Series(dtype=float)), errors="coerce").dropna()
    if ticker != "All" and "Ticker" in df:
        ref_values = pd.to_numeric(df.loc[df["Ticker"].astype(str)==ticker, "Reference Price"], errors="coerce").dropna()
    if not ref_values.empty:
        default_price = float(ref_values.median())
        pinpoint_price = st.sidebar.number_input("Underlying pinpoint price", min_value=0.0, value=default_price, step=0.01, format="%.2f")
        pinpoint_tolerance = st.sidebar.number_input("Tolerance (±)", min_value=0.0, value=0.0, step=0.05, format="%.2f")
        st.sidebar.caption("Uses QuantData's Reference Price (underlying spot at the print).")

exp_values = sorted(df["Expiration Date"].dropna().dt.date.unique()) if "Expiration Date" in df else []
if exp_values:
    exp_range = st.sidebar.date_input("Expiration date range", value=(exp_values[0], exp_values[-1]),
                                     min_value=exp_values[0], max_value=exp_values[-1])
else:
    exp_range = None

calls_puts = st.sidebar.multiselect("Contract type", ["CALL","PUT"], default=["CALL","PUT"])
trade_types = sorted(df["Trade Type"].dropna().unique())
selected_trade_types = st.sidebar.multiselect("Trade Type", trade_types, default=trade_types)

st.sidebar.markdown("---")
st.sidebar.subheader("Flow toggles")
show_sweeps = st.sidebar.toggle("Sweeps", True)
show_blocks = st.sidebar.toggle("Blocks", True)
show_open_positions = st.sidebar.toggle("Open Positions", True)
show_split = st.sidebar.toggle("Split / other", False)
st.sidebar.caption("Sweeps and blocks use Consolidation Type. Open positions use Is Opening Position.")

# Aggressor-side filter: ask-side prints are generally buyer-initiated;
# bid-side prints are generally seller-initiated. Midpoint/other is not directional.
st.sidebar.markdown("---")
st.sidebar.subheader("📈 Bought / Sold")
side_filter = st.sidebar.multiselect(
    "Initiator side",
    ["Buyer initiated (Ask)", "Seller initiated (Bid)", "Midpoint / Other"],
    default=["Buyer initiated (Ask)", "Seller initiated (Bid)", "Midpoint / Other"]
)
st.sidebar.caption("Ask-side = buyer initiated; bid-side = seller initiated. This is an execution-side inference, not proof of opening/closing intent.")

# ----- Filtering -----
f = df.copy()
if ticker != "All" and "Ticker" in f: f = f[f["Ticker"].astype(str) == ticker]
if pinpoint_enabled and pinpoint_price is not None and "Reference Price" in f:
    ref = pd.to_numeric(f["Reference Price"], errors="coerce")
    f = f[ref.between(pinpoint_price-pinpoint_tolerance, pinpoint_price+pinpoint_tolerance)]
if calls_puts and "Contract Type" in f: f = f[f["Contract Type"].isin(calls_puts)]

if "Side Code" in f:
    side = f["Side Code"].fillna("").astype(str).str.upper()
    side_labels = pd.Series("Midpoint / Other", index=f.index)
    side_labels.loc[side.isin(["A", "AA"])] = "Buyer initiated (Ask)"
    side_labels.loc[side.isin(["B", "BB"])] = "Seller initiated (Bid)"
    if side_filter:
        f = f[side_labels.loc[f.index].isin(side_filter)]

if selected_trade_types and "Trade Type" in f: f = f[f["Trade Type"].isin(selected_trade_types)]
if exp_range and isinstance(exp_range, (tuple,list)) and len(exp_range)==2 and "Expiration Date" in f:
    start, end = exp_range
    f = f[f["Expiration Date"].dt.date.between(start,end)]

cons = f["Consolidation Type"].fillna("UNKNOWN").astype(str).str.upper()
opening = f["Is Opening Position"].fillna("NO").astype(str).str.upper()
mask = pd.Series(False, index=f.index)
if show_sweeps: mask |= cons.eq("SWEEP")
if show_blocks: mask |= cons.eq("BLOCK")
if show_split: mask |= cons.eq("SPLIT")
if show_open_positions: mask |= opening.eq("YES")
f = f[mask]

# ----- Summary metrics -----
premium_col = "Premium Price" if "Premium Price" in f else None
premium = f[premium_col].fillna(0).sum() if premium_col else 0
n_trades = len(f)
n_tickers = f["Ticker"].nunique() if "Ticker" in f else 0
n_open = (f["Is Opening Position"].astype(str).str.upper()=="YES").sum() if "Is Opening Position" in f else 0

m1,m2,m3,m4 = st.columns(4)
m1.metric("Total Premium", f"${premium:,.0f}")
m2.metric("Flow Records", f"{n_trades:,}")
m3.metric("Tickers", f"{n_tickers:,}")
m4.metric("Opening Positions", f"{n_open:,}")

st.markdown("---")

# ----- Order type bucket classification -----
# QuantData file uses Trade Type values such as AUTO, SPRD_LEG_AUTO, FLR,
# SPRD_FLR, SPRD_FLR_PP, SPRD_LEG_FLR. Make grouping transparent and adjustable.
def bucket_trade_type(x):
    x = str(x).upper()
    if "AUTO" in x and ("SPRD" in x or "TIED" in x or x.startswith("MULTI")):
        return "MULTI AUTO"
    if x == "AUTO" or x == "TIED_AUTO":
        return "AUTO"
    if "FLR" in x or x in {"M2MFLR","M2M_FLR"}:
        return "M2MFLR"
    if "AUCT" in x: return "AUCTION"
    if "COB" in x: return "COB"
    if "ISO" in x: return "ISO"
    if "CROSS" in x: return "CROSS"
    return x or "UNKNOWN"

f["Order Type Bucket"] = f["Trade Type"].map(bucket_trade_type)
bucket_order = ["M2MFLR","AUTO","MULTI AUTO"]
avail_buckets = [x for x in bucket_order if x in f["Order Type Bucket"].unique()]
other_buckets = sorted(set(f["Order Type Bucket"].unique()) - set(bucket_order))
display_buckets = avail_buckets + other_buckets

st.subheader("Order Type Bucket by Expiration")
if f.empty:
    st.warning("No records match the selected filters. Turn on a flow type or broaden filters.")
else:
    agg = f.groupby(["Expiration Date","Order Type Bucket"], dropna=False).agg(
        Premium=("Premium Price","sum"),
        Volume=("Volume","sum"),
        OI=("Open Interest","sum"),
        Trades=("Trade ID","count"),
    ).reset_index() if "Trade ID" in f else f.groupby(["Expiration Date","Order Type Bucket"]).agg(
        Premium=("Premium Price","sum"), Volume=("Volume","sum"), OI=("Open Interest","sum")
    ).reset_index()
    agg["Expiration"] = agg["Expiration Date"].dt.strftime("%Y-%m-%d")
    tab1,tab2,tab3 = st.tabs(["Premium","Volume","Trade Count"])
    with tab1:
        fig = px.bar(agg, x="Expiration", y="Premium", color="Order Type Bucket",
                     barmode="group", category_orders={"Order Type Bucket":display_buckets},
                     title="Premium by Expiration & Order Type")
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0f17", plot_bgcolor="#0b0f17")
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        fig = px.bar(agg, x="Expiration", y="Volume", color="Order Type Bucket",
                     barmode="group", category_orders={"Order Type Bucket":display_buckets},
                     title="Volume by Expiration & Order Type")
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0f17", plot_bgcolor="#0b0f17")
        st.plotly_chart(fig, use_container_width=True)
    with tab3:
        if "Trades" in agg:
            fig = px.bar(agg, x="Expiration", y="Trades", color="Order Type Bucket",
                         barmode="group", category_orders={"Order Type Bucket":display_buckets},
                         title="Record Count by Expiration & Order Type")
            fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0f17", plot_bgcolor="#0b0f17")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Trade ID column unavailable for record count.")

st.subheader("Bucket Summary")
summary = f.groupby("Order Type Bucket").agg(
    Premium=("Premium Price","sum"),
    Volume=("Volume","sum"),
    Average_OI=("Open Interest","mean"),
    Records=("Order Type Bucket","size")
).sort_values("Premium", ascending=False)
summary["Premium"] = summary["Premium"].map(lambda x: f"${x:,.0f}")
summary["Average_OI"] = summary["Average_OI"].round(0)
st.dataframe(summary, use_container_width=True)

st.subheader("Filtered Flow Records")
cols = [c for c in ["Trade Time","Ticker","Expiration Date","Days Until Expiration","Strike Price",
                     "Contract Type","Reference Price","Trade Type","Order Type Bucket","Consolidation Type",
                     "Side Code","Premium Price","Volume","Open Interest","Is Opening Position",
                     "Is Golden Sweep"] if c in f.columns]
display_df = f[cols].sort_values("Premium Price", ascending=False).rename(columns={"Reference Price":"🎯 Pinpoint Price"})
if "Side Code" in display_df.columns:
    display_df["Initiator"] = display_df["Side Code"].map(
        {"A":"Buyer initiated (Ask)", "AA":"Buyer initiated (Ask)",
         "B":"Seller initiated (Bid)", "BB":"Seller initiated (Bid)",
         "M":"Midpoint / Other"}
    ).fillna("Midpoint / Other")
st.dataframe(display_df, use_container_width=True, height=450)

csv = f.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download filtered flow CSV", csv, "filtered_options_flow.csv", "text/csv")
