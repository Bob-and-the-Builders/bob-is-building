import streamlit as st
from datetime import datetime, timedelta, timezone
from revenue_split.revenue_split import finalize_revenue_window

UTC = timezone.utc
st.set_page_config(page_title="Admin • Revenue Window", layout="centered")
st.title("Admin: Revenue Window (Shorts)")

with st.form("rw"):
    now = datetime.now(UTC).replace(microsecond=0, second=0)
    end = st.datetime_input("Window end (UTC)", value=now)
    start = st.datetime_input("Window start (UTC)", value=now - timedelta(days=1))
    st.subheader("Window accounting (cents)")
    gross = st.number_input("Gross revenue", min_value=0, value=200_000)  # $2,000
    taxes = st.number_input("Taxes", min_value=0, value=10_000)
    store = st.number_input("App store fees", min_value=0, value=20_000)
    refunds = st.number_input("Refunds", min_value=0, value=5_000)
    st.subheader("Policy knobs")
    pool_pct = st.slider("Base pool % (of net)", 0.0, 1.0, 0.45, 0.01)
    margin_target = st.slider("Margin target (of gross)", 0.0, 1.0, 0.60, 0.01)
    platform_fee_pct = st.slider("Platform fee %", 0.0, 0.5, 0.10, 0.01)
    reserve_pct = st.slider("Safety reserve %", 0.0, 0.5, 0.10, 0.01)
    min_payout = st.number_input("Min payout (cents)", min_value=0, value=1000)
    hold_days = st.number_input("Reserve hold days", min_value=0, value=14)
    submitted = st.form_submit_button("Run allocation")

if submitted:
    out = finalize_revenue_window(
        start,
        end,
        gross_revenue_cents=int(gross),
        taxes_cents=int(taxes),
        app_store_fees_cents=int(store),
        refunds_cents=int(refunds),
        pool_pct=float(pool_pct),
        margin_target=float(margin_target),
        risk_reserve_pct=float(reserve_pct),
        platform_fee_pct=float(platform_fee_pct),
        min_payout_cents=int(min_payout),
        hold_days=int(hold_days),
    )
    st.success("Allocation complete.")
    st.subheader("Revenue window")
    st.json(out["revenue_window"])
    st.subheader("Video allocations (first 50)")
    st.json(out["video_rev_shares"][:50])
    st.subheader("Creator payouts")
    st.json(out["creator_payouts"])
