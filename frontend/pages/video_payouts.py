import os
import sys
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from supabase import Client

# Ensure project root on sys.path (optional but handy)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

st.set_page_config(page_title="Video Payouts", layout="wide")

supabase: Client = st.session_state.get("supabase")

# ---------- helpers ----------
def resolve_creator_id(sb: Client, user: dict) -> int | None:
    # prefer session creator_id if valid
    cid = st.session_state.get("creator_id")
    if isinstance(cid, int):
        return cid
    # else map auth email -> user_info.user_id (your numeric users.id)
    email = (user or {}).get("email")
    if email:
        res = sb.table("user_info").select("user_id").eq("email", email).single().execute()
        uid = (res.data or {}).get("user_id")
        if uid is not None:
            return int(uid)
    return None

@st.cache_data(ttl=600)
def get_payout_data(recipient_id: int, refresh_key: int = 0):
    if not supabase or not recipient_id:
        return None
    # stored balance (optional)
    bal = 0
    try:
        resp = supabase.table("users").select("current_balance").eq("id", recipient_id).single().execute()
        if resp.data:
            bal = resp.data.get("current_balance", 0) or 0
    except Exception:
        pass
    # all transactions for this recipient
    tx = supabase.table("transactions").select("*").eq("recipient", recipient_id).execute().data or []
    return {"stored_balance_cents": int(bal or 0), "transactions": pd.DataFrame(tx)}

# ---------- UI ----------
st.title("💰 Video Payouts")

user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to view your payout information.")
    st.stop()

creator_id = resolve_creator_id(supabase, user or {})
if not creator_id:
    st.error("Could not resolve your creator account.")
    st.stop()

st.session_state.setdefault("_tx_refresh", 0)
colR1, colR2 = st.columns([1, 6])
with colR1:
    if st.button("↻ Refresh data"):
        st.session_state["_tx_refresh"] += 1
        get_payout_data.clear()
        st.rerun()

data = get_payout_data(creator_id, st.session_state["_tx_refresh"])
if not data:
    st.warning("Could not load payout data.")
    st.stop()

transactions_df = data["transactions"]

# ---------- metrics (inflow/outflow) ----------
if not transactions_df.empty:
    if "amount_cents" not in transactions_df.columns:
        transactions_df["amount_cents"] = 0
    transactions_df["amount_cents"] = pd.to_numeric(transactions_df["amount_cents"], errors="coerce").fillna(0)

    inflow_cents = transactions_df.loc[transactions_df["direction"].eq("inflow"), "amount_cents"].sum() if "direction" in transactions_df.columns else 0
    outflow_cents = transactions_df.loc[transactions_df["direction"].eq("outflow"), "amount_cents"].sum() if "direction" in transactions_df.columns else 0
    net_balance_cents = int(inflow_cents - outflow_cents)
else:
    inflow_cents = outflow_cents = net_balance_cents = 0

st.header("Your Financial Overview")
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Current Balance", f"${net_balance_cents/100:,.2f}")
with c2:
    st.metric("Total Earned (Inflow)", f"${inflow_cents/100:,.2f}")
with c3:
    st.metric("Total Paid Out (Outflow)", f"${outflow_cents/100:,.2f}")

st.write("---")

# ---------- Transaction History ----------
st.subheader("Transaction History")

if not transactions_df.empty:
    display_df = transactions_df.copy()

    # Friendly labels
    if "payment_type" in display_df.columns:
        display_df["payment_type"] = display_df["payment_type"].replace({
            "revenue_split": "Revenue Split (Daily)",
            "revenue_split_monthly": "Revenue Split (Monthly)",
            "bank_transfer": "Payout: Bank Transfer",
            "card": "Payout: Card",
            "wallet": "Payout: Wallet",
            "paypal": "Payout: PayPal",
        })

    # money column (USD)
    if "amount_cents" not in display_df.columns:
        display_df["amount_cents"] = 0
    display_df["amount_cents"] = pd.to_numeric(display_df["amount_cents"], errors="coerce").fillna(0)
    display_df["Amount (USD)"] = display_df["amount_cents"] / 100.0

    # Dates: parse & sort, then produce clean string (handles NULLs)
    if "created_at" in display_df.columns:
        # stringify and clean up common missing markers
        display_df["created_at_raw"] = (
            display_df["created_at"]
            .astype(str)
            .replace({"NaT": "—", "None": "—", "": "—"})
        )

        # Optional: if your DB stores ISO timestamps, lexicographic sort works fine
        display_df = display_df.sort_values("created_at_raw", ascending=False)
    else:
        display_df["created_at_raw"] = "—"

    # Only show the raw column (rename in UI)
    cols = [c for c in ["created_at_raw", "Amount (USD)", "direction", "payment_type", "status"] if c in display_df.columns]

    st.dataframe(
        display_df[cols],
        use_container_width=True,
        column_config={
            "created_at_raw": st.column_config.TextColumn("created_at (raw)"),
            "Amount (USD)": st.column_config.NumberColumn(format="$%.2f"),
            "direction": st.column_config.TextColumn("Direction", help="inflow = earnings, outflow = payouts"),
            "payment_type": st.column_config.TextColumn("Type"),
            "status": st.column_config.TextColumn("Status"),
        },
    )
else:
    st.info("You have no transaction history yet. Keep creating to start earning!")

st.write("---")

# ---------- Payout action (outflow) ----------
st.subheader("Request a Payout")

available_usd = round(max(0, net_balance_cents) / 100.0, 2)
can_withdraw = available_usd >= 5.00
st.write(f"Your current available balance: **${available_usd:,.2f}**")

payment_method = st.selectbox(
    "Payout method",
    options=["bank_transfer", "card", "wallet", "paypal"],
    index=0,
    help="Choose where we should send your payout.",
)

if can_withdraw:
    amount_to_withdraw = st.number_input(
        "Amount to withdraw (USD)",
        min_value=5.00,
        max_value=available_usd,
        value=available_usd,
        step=5.00,
        format="%.2f",
    )
else:
    st.info("Minimum withdrawal is $5.00.")
    amount_to_withdraw = 0.00

if st.button("Request Payout", disabled=not can_withdraw):
    try:
        amount_cents = int(round(amount_to_withdraw * 100))
        # Optional KYC checks
        kyc_level = (supabase.table("users").select("kyc_level")
                     .eq("id", creator_id).single().execute().data or {}).get("kyc_level", 0)

        if kyc_level == 2 and amount_cents >= 50000:
            st.warning("Payouts of $500+ require KYC Level 3.")
        elif kyc_level == 1 and amount_cents >= 10000:
            st.warning("Payouts of $100+ require KYC Level 2.")
        else:
            supabase.table("transactions").insert({
                "recipient": creator_id,
                "amount_cents": amount_cents,
                "payment_type": payment_method,
                "direction": "outflow",
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            st.success(f"Payout request for ${amount_to_withdraw:,.2f} submitted.")
            get_payout_data.clear()
            st.session_state["_tx_refresh"] += 1
            st.rerun()
    except Exception as e:
        st.error(f"Could not submit payout request: {e}")
