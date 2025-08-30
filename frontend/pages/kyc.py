import streamlit as st
from supabase import Client

supabase: Client = st.session_state['supabase']
user = st.session_state.get("user")

# your code here
# entrypoint file guarantees that supabase and user will be in session state
# else your page code will not even run