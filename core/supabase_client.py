import os
from typing import Optional

import streamlit as st
from supabase import Client, create_client


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    """Return a cached Supabase client using env credentials.

    Expected env vars:
    - SUPABASE_URL
    - SUPABASE_SECRET (service role or anon key)
    """
    url: Optional[str] = os.getenv("SUPABASE_URL")
    key: Optional[str] = os.getenv("SUPABASE_SECRET") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL and/or SUPABASE_SECRET in environment."
        )
    return create_client(url, key)

