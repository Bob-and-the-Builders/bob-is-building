import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def sign_up(email: str, password: str):
    try:
        user = supabase.auth.sign_up({"email": email, "password": password})
        return user
    except Exception as e:
        st.error(f"Error signing up: {e}")

def sign_in(email: str, password: str):
    try:
        user = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return user
    except Exception as e:
        st.error(f"Error signing in: {e}")
        return None
    

st.title("Welcome to TikTok Content Creator Portal")
# Show login/signup options
tab1, tab2 = st.tabs(["Sign In", "Sign Up"])

with tab1:
    st.subheader("Sign In")
    email = st.text_input("Email", key="signin_email")
    password = st.text_input("Password", type="password", key="signin_password")
    
    if st.button("Sign In", key="signin_button"):
        if email and password:
            user = sign_in(email, password)
            if user and user.user:
                st.session_state['user'] = user.user
                st.success("Successfully signed in!")
                st.rerun()
        else:
            st.error("Please enter both email and password")

with tab2:
    st.subheader("Sign Up")
    email = st.text_input("Email", key="signup_email")
    password = st.text_input("Password", type="password", key="signup_password")
    
    if st.button("Sign Up", key="signup_button"):
        if email and password:
            user = sign_up(email, password)
            if user:
                st.success("Successfully signed up! Please check your email for verification.")
        else:
            st.error("Please enter both email and password")

# def main():
#     st.title("Welcome to the TikTok Content Creator Portal!")
#     st.success(f"You are logged in as {st.session_state['user'].email}")
#     if st.button("Sign Out"):
#             sign_out()
