import os
import sys
from datetime import date

import pandas as pd
import streamlit as st
from supabase import Client

# --- Ensure project root on sys.path (so other local packages can be imported if needed) ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -----------------------------
# Streamlit + Supabase init
# -----------------------------
st.set_page_config(page_title="Video Payouts", layout="wide")

# Supabase client & session user should already be set in st.session_state by your main app
supabase: Client = st.session_state.get("supabase")

# -----------------------------
# Data fetch helpers
# -----------------------------
@st.cache_data(ttl=600)
def get_payout_data(user_id: int):
    """
    Returns the user's balance (as stored in users.current_balance) and all transactions
    addressed to them from the 'transactions' table.
    """
    if not supabase or not user_id:
        return None

    try:
        # Current stored balance (optional; we'll also compute from inflow/outflow for display)
        current_balance_cents = 0
        try:
            resp = (
                supabase.table("users")
                .select("current_balance")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if getattr(resp, "data", None):
                current_balance_cents = resp.data.get("current_balance", 0) or 0
        except Exception:
            current_balance_cents = 0

        # All transactions for this user
        tx_resp = (
            supabase.table("transactions")
            .select("*")
            .eq("recipient", user_id)
            .execute()
        )
        transactions = tx_resp.data or []
        transactions_df = pd.DataFrame(transactions)

        return {
            "stored_balance_cents": int(current_balance_cents or 0),
            "transactions": transactions_df,
        }
    except Exception as e:
        st.error(f"Error fetching payout data: {e}")
        return None


# -----------------------------
# UI (Creator only)
# -----------------------------
st.title("💰 Video Payouts")

# Auth gate
user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to view your payout information.")
    st.stop()

# Resolve the creator's users.id (you can replace this with your own mapping logic if needed)
user_id = st.session_state.get("creator_id") or (user.get("id") if isinstance(user, dict) else None)
if not user_id:
    st.warning("No creator_id found in session.")
    st.stop()

data = get_payout_data(user_id)
if not data:
    st.warning("Could not load payout data.")
    st.stop()

stored_balance_cents = data["stored_balance_cents"]
transactions_df = data["transactions"]

# -----------------------------
# Metrics (using direction enum)
# -----------------------------
if not transactions_df.empty:
    # Ensure columns exist
    if "amount_cents" not in transactions_df.columns:
        transactions_df["amount_cents"] = 0
    if "direction" not in transactions_df.columns:
        # fallback for older rows (treat unknown as outflow to be conservative)
        transactions_df["direction"] = "outflow"

    inflow_cents = transactions_df.loc[
        transactions_df["direction"] == "inflow", "amount_cents"
    ].fillna(0).sum()

    outflow_cents = transactions_df.loc[
        transactions_df["direction"] == "outflow", "amount_cents"
    ].fillna(0).sum()

    net_balance_cents = int(inflow_cents - outflow_cents)
    total_transactions = len(transactions_df)
else:
    inflow_cents = 0
    outflow_cents = 0
    net_balance_cents = 0
    total_transactions = 0

st.header("Your Financial Overview")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Current Balance", f"${net_balance_cents/100:,.2f}")
with col2:
    st.metric("Total Earned (Inflow)", f"${inflow_cents/100:,.2f}")
with col3:
    st.metric("Total Paid Out (Outflow)", f"${outflow_cents/100:,.2f}")

# (Optional) show stored balance for debugging differences
with st.expander("Debug: Stored balance vs computed"):
    st.write(
        {
            "users.current_balance (stored)": f"${stored_balance_cents/100:,.2f}",
            "computed balance (inflow - outflow)": f"${net_balance_cents/100:,.2f}",
        }
    )

st.write("---")

# --- Transaction history ---
st.subheader("Transaction History")

if not transactions_df.empty:
    display_df = transactions_df.copy()

    # Ensure required columns exist / types
    if "amount_cents" not in display_df.columns:
        display_df["amount_cents"] = 0
    display_df["amount_cents"] = pd.to_numeric(display_df["amount_cents"], errors="coerce").fillna(0)

    if "direction" not in display_df.columns:
        display_df["direction"] = "outflow"  # fallback for legacy rows

    # Friendly labels for payment_type
    if "payment_type" in display_df.columns:
        display_df["payment_type"] = display_df["payment_type"].replace({
            "revenue_split": "Revenue Split (Daily)",
            "revenue_split_monthly": "Revenue Split (Monthly)",
            "bank_transfer": "Payout: Bank Transfer",
            "card": "Payout: Card",
            "wallet": "Payout: Wallet",
            "paypal": "Payout: PayPal",
        })

    # Amount in USD
    display_df["Amount (USD)"] = display_df["amount_cents"] / 100.0

    # ---- Dates: parse → sort → make tz-naive for Streamlit ----
    if "created_at" in display_df.columns:
        display_df["created_at"] = pd.to_datetime(display_df["created_at"], errors="coerce", utc=True)
        # show/sort by UTC (or change "UTC" to your tz)
        # create a tz-naive column for Streamlit's DatetimeColumn
        display_df["display_date"] = (
            display_df["created_at"]
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
        )
        display_df = display_df.sort_values("created_at", ascending=False)
    else:
        display_df["display_date"] = pd.NaT

    # Columns to show
    cols = [c for c in ["display_date", "Amount (USD)", "direction", "payment_type", "status"] if c in display_df.columns]

    st.dataframe(
        display_df[cols],
        use_container_width=True,
        column_config={
            "display_date": st.column_config.DatetimeColumn("Date"),
            "Amount (USD)": st.column_config.NumberColumn(format="$%.2f"),
            "direction": st.column_config.TextColumn("Direction", help="inflow = earnings, outflow = payouts"),
            "payment_type": st.column_config.TextColumn("Type"),
            "status": st.column_config.TextColumn("Status"),
        },
    )
else:
    st.info("You have no transaction history yet. Keep creating to start earning!")
    
# --- Payout action (creates outflow) ---
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
    # User has at least $5 → allow entry
    amount_to_withdraw = st.number_input(
        "Amount to withdraw (USD)",
        min_value=5.00,
        max_value=available_usd,
        value=available_usd,            # default to max available
        step=5.00,
        format="%.2f",
        disabled=False,
    )
else:
    # Not enough funds → lock the control at 0
    st.info("Minimum withdrawal is $5.00.")
    amount_to_withdraw = st.number_input(
        "Amount to withdraw (USD)",
        min_value=0.00,
        max_value=available_usd,        # 0.00
        value=available_usd,            # 0.00
        step=1.00,
        format="%.2f",
        disabled=True,
    )

if st.button("Request Payout", disabled=not can_withdraw):
    try:
        amount_cents = int(round(amount_to_withdraw * 100))

        # Resolve users.id via user_info.email
        email = getattr(user, "email", None)
        ui = (
            supabase.table("user_info")
            .select("user_id")
            .eq("email", email)
            .single()
            .execute()
        )
        recipient_id = (ui.data or {}).get("user_id")

        if not recipient_id:
            st.error("Could not resolve your creator account.")
        else:
            # Optional KYC checks
            resp = (
                supabase.table("users")
                .select("kyc_level")
                .eq("id", user_id)
                .single()
                .execute()
            )
            kyc_level = (resp.data or {}).get("kyc_level", 0)

            if kyc_level == 2 and amount_cents >= 50000:
                st.warning("Payouts of $500+ require KYC Level 3.")
            elif kyc_level == 1 and amount_cents >= 10000:
                st.warning("Payouts of $100+ require KYC Level 2.")
            else:
                supabase.table("transactions").insert(
                    {
                        "recipient": int(recipient_id),
                        "amount_cents": amount_cents,
                        "payment_type": payment_method,  # e.g., bank_transfer
                        "direction": "outflow",          # NEW: enum you added
                        "status": "pending",
                    }
                ).execute()
                st.success(f"Payout request for ${amount_to_withdraw:,.2f} submitted.")
                get_payout_data.clear()  # refresh cache on next render
    except Exception as e:
        st.error(f"Could not submit payout request: {e}")
