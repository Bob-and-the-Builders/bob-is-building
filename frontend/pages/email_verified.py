import streamlit as st

st.title("Email Verified")
st.success("Your email has been verified successfully!")
st.page_link("pages/auth.py", label="Login now", icon=":material/login:")