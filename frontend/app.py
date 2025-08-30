import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
st.session_state['supabase'] = supabase

# Ensure session state key exists early to avoid KeyError on first load
if 'user' not in st.session_state:
    st.session_state['user'] = None

def sign_out():
    try:
        supabase.auth.sign_out()
        st.success("Successfully signed out!")
        # Safely remove user from session state
        if 'user' in st.session_state:
            del st.session_state['user']
        st.rerun()
    except Exception as e:
        st.error(f"Error signing out: {e}")

def get_current_user():
    try:
        user = supabase.auth.get_user()
        return user
    except Exception as e:
        return None

def get_creator_id_from_email(email: str) -> int | None:
    """SELECT user_id FROM user_info WHERE email = <email>"""
    if not email:
        return None
    try:
        res = supabase.table("user_info").select("user_id").eq("email", email).single().execute()
        if res and getattr(res, "data", None):
            return res.data.get("user_id")
    except Exception as e:
        st.warning(f"Could not resolve creator_id from user_info: {e}")
    return None

# Define the pages
login_page = st.Page("pages/auth.py", title="Log in", icon=":material/login:")
signout_page = st.Page(sign_out, title="Sign out", icon=":material/logout:")

dashboard = st.Page("pages/creator_dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True)
upload_video = st.Page("pages/upload_video.py", title="Upload Video", icon=":material/upload:")
payout = st.Page("pages/video_payouts.py", title="Payout", icon=":material/money:")
kyc_page = st.Page("pages/kyc.py", title="KYC Verification", icon=":material/verified_user:")
email_verified = st.Page("pages/email_verified.py", title="Email Verified", icon=":material/email:")

# Check if user is already logged in (ensured above as well)
if 'user' not in st.session_state:
    st.session_state['user'] = None

# Get current user
current_user = get_current_user()
if current_user and current_user.user:
    st.session_state['user'] = current_user.user

# Set up navigation
if st.session_state['user']:
    creator_id_lookup = get_creator_id_from_email(getattr(st.session_state['user'], "email", None))
    if creator_id_lookup is None:
        # Fallback to auth user id if no user_info row is found
        creator_id_lookup = getattr(st.session_state['user'], "id", None)
        if creator_id_lookup is None:
            st.error("Unable to determine creator_id. Please ensure your user has a user_info row.")
            st.stop()
    st.session_state['creator_id'] = creator_id_lookup

    pg = st.navigation(
        {
            f"Hello {st.session_state['user'].email}": [signout_page],
            "Content Creator Portal": [dashboard, upload_video, payout, kyc_page]
        }
    )
else:
    pg = st.navigation([login_page, email_verified], position="hidden")

# Run the selected page
pg.run()
