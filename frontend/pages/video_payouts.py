import streamlit as st
import pandas as pd
from supabase import Client

# --- Boilerplate and Supabase Initialization ---
st.set_page_config(page_title="Video Payouts", layout="wide")

supabase: Client = st.session_state.get('supabase')

st.title("💰 Video Payouts")

# --- Authentication Gate  ---
user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to view your payout information.")
    st.stop()

# --- New Data Fetching Function for Payouts ---
@st.cache_data(ttl=600)
def get_payout_data(user_id: int):
    """
    Fetches financial data for the given creator, including their
    current balance and transaction history.
    """
    if not supabase or not user_id:
        st.warning("Supabase client not initialized or user not found.")
        return None
    
    try:
        # Fetch the user's current balance (if present) from 'users'
        current_balance_cents = 0
        try:
            user_response = (
                supabase.table("users")
                .select("current_balance")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if getattr(user_response, "data", None):
                current_balance_cents = user_response.data.get("current_balance", 0) or 0
        except Exception:
            # If the column does not exist or call fails, we will compute a fallback below
            current_balance_cents = 0

        # Fetch all transactions for the creator from 'transactions' table using 'user_id'
        tx_resp = supabase.table("transactions").select("*").eq("recipient", user_id).execute()
        transactions = tx_resp.data or []
        transactions_df = pd.DataFrame(transactions)

        # Fallback balance computation if not in users.current_balance
        if not current_balance_cents:
            if not transactions_df.empty:
                # Available = sum of payout amounts not on hold (exclude reserves and future holds)
                now_iso = pd.Timestamp.utcnow().tz_localize(None)
                df = transactions_df.copy()
                # Parse hold_until if present
                if "hold_until" in df.columns:
                    df["hold_until_ts"] = pd.to_datetime(df["hold_until"], errors="coerce", utc=True).dt.tz_convert(None)
                else:
                    df["hold_until_ts"] = pd.NaT
                is_payout = df.get("type", pd.Series([])).eq("payout") if "type" in df.columns else pd.Series(False, index=df.index)
                not_on_hold = (~df.get("status", pd.Series([])).eq("on_hold")) if "status" in df.columns else pd.Series(True, index=df.index)
                hold_released = (df["hold_until_ts"].isna()) | (df["hold_until_ts"] <= now_iso)
                mask = is_payout & not_on_hold & hold_released
                current_balance_cents = int(df.loc[mask, "amount_cents"].fillna(0).sum())

        return {"balance_cents": int(current_balance_cents or 0), "transactions": transactions_df}
    except Exception as e:
        st.error(f"Error fetching payout data from Supabase: {e}")
        return None

# --- Fetch and Load Data ---
user_id = st.session_state.get('creator_id') or (user.get('id') if isinstance(user, dict) else None)
if not user_id:
    st.warning("No creator_id found in session.")
    st.stop()
payout_data = get_payout_data(user_id)

if not payout_data:
    st.warning("Could not load your payout data. Please try again later.")
    st.stop()

balance_cents = payout_data["balance_cents"]
transactions_df = payout_data["transactions"]

# --- Payouts Dashboard Layout ---
st.header("Your Financial Overview")

# Calculate key metrics
if not transactions_df.empty:
    total_earned_cents = transactions_df['amount_cents'].sum()
    total_transactions = len(transactions_df)
    avg_payout_cents = transactions_df['amount_cents'].mean()
else:
    total_earned_cents = 0
    total_transactions = 0
    avg_payout_cents = 0

col1, col2, col3 = st.columns(3)

with col1:
    # Format cents to dollars for display
    st.metric(label="Current Balance", value=f"${balance_cents / 100:,.2f}")
with col2:
    st.metric(label="Total Earned", value=f"${total_earned_cents / 100:,.2f}")
with col3:
    st.metric(label="Total Transactions", value=total_transactions)

st.write("---")

# --- Transaction History Table ---
st.subheader("Transaction History")

if not transactions_df.empty:
    # Create a copy to avoid modifying the cached DataFrame
    display_df = transactions_df.copy()

    # Convert amount from cents to dollars for display
    if 'amount_cents' in display_df.columns:
        display_df['Amount (USD)'] = display_df['amount_cents'] / 100
    else:
        display_df['Amount (USD)'] = 0.0

    # Preferred columns with safe fallbacks
    cols = []
    if 'created_at' in display_df.columns: cols.append('created_at')
    cols.append('Amount (USD)')
    if 'status' in display_df.columns: cols.append('status')
    if 'type' in display_df.columns: cols.append('type')
    if 'hold_until' in display_df.columns: cols.append('hold_until')

    if 'created_at' in display_df.columns:
        display_df = display_df.sort_values('created_at', ascending=False)

    st.dataframe(
        display_df[cols],
        use_container_width=True,
        column_config={
            "created_at": st.column_config.DatetimeColumn("Date", help="The date and time of the transaction."),
            "Amount (USD)": st.column_config.NumberColumn(format="$%.2f", help="The transaction amount in US dollars."),
            "status": st.column_config.TextColumn("Status", help="The current status of the transaction (e.g., pending, on_hold, completed)."),
            "type": st.column_config.TextColumn("Type", help="Transaction type (payout, reserve, etc.)."),
            "hold_until": st.column_config.DatetimeColumn("Hold Until", help="Funds are released after this time (UTC)."),
        }
    )
else:
    st.info("You have no transaction history yet. Keep creating to start earning!")

st.write("---")

# --- Payout Action Section ---
st.subheader("Request a Payout")
st.write(f"Your current available balance for withdrawal is **${balance_cents / 100:,.2f}**.")


amount_to_withdraw = st.number_input(
    label="Amount to withdraw (USD)",
    min_value=5.00,
    max_value=float(balance_cents / 100),
    value=max(5.00, float(balance_cents / 100)), # Default to max available or $5
    step=5.00,
    format="%.2f",
    disabled=(balance_cents < 500) # Disable if balance is less than $5
)
if st.button("Request Payout", disabled=(balance_cents < 500)):
    # In a real app, this is where you would trigger a Supabase Edge Function
    # or an API call to your backend to process the payout.
    st.success(f"Your payout request for ${amount_to_withdraw:,.2f} has been submitted for processing!")
   
