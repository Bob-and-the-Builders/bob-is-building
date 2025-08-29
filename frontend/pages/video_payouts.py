import streamlit as st
import pandas as pd
from supabase import Client

# --- Boilerplate and Supabase Initialization ---
st.set_page_config(page_title="Video Payouts", layout="wide")

supabase: Client = st.session_state['supabase']

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
        # Fetch the user's current balance from the 'users' table
        user_response = supabase.table("users").select("current_balance").eq("id", user_id).single().execute()
        current_balance_cents = user_response.data.get('current_balance', 0) if user_response.data else 0

        # Fetch all transactions for the creator from the 'transactions' table
        # We assume the 'recipient' column in 'transactions' matches the user's 'id'
        transactions_response = supabase.table("transactions").select("*").eq("recipient", user_id).execute()
        
        transactions_df = pd.DataFrame(transactions_response.data)

        return {
            "balance_cents": current_balance_cents,
            "transactions": transactions_df
        }
    except Exception as e:
        st.error(f"Error fetching payout data from Supabase: {e}")
        return None

# --- Fetch and Load Data ---
user_id = st.session_state['creator_id']
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
    display_df['Amount (USD)'] = display_df['amount_cents'] / 100

    st.dataframe(
        display_df[['created_at', 'Amount (USD)', 'status', 'payment_type']].sort_values('created_at', ascending=False),
        use_container_width=True,
        column_config={
            "created_at": st.column_config.DatetimeColumn("Date", help="The date and time of the transaction."),
            "Amount (USD)": st.column_config.NumberColumn(format="$%.2f", help="The transaction amount in US dollars."),
            "status": st.column_config.TextColumn("Status", help="The current status of the transaction (e.g., completed, pending)."),
            "payment_type": st.column_config.TextColumn("Type", help="The type of payment (e.g., video earning, bonus).")
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
   