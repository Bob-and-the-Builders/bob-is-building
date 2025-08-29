import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

# Define the pages
login_page = st.Page("pages/auth.py", title="Log in", icon=":material/login:")
signout_page = st.Page(sign_out, title="Sign out", icon=":material/logout:")

dashboard = st.Page("pages/creator_dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True)
upload_video = st.Page("pages/upload_video.py", title="Upload Video", icon=":material/upload:")
payout = st.Page("pages/video_payouts.py", title="Payout", icon=":material/money:")
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
    pg = st.navigation(
        {
            "Account": [signout_page],
            "Content Creator Portal": [dashboard, upload_video, payout]
        }
    )
else:
    pg = st.navigation([login_page], position="hidden")

# Run the selected page
pg.run()
