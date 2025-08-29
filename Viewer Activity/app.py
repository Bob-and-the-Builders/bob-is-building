import os
from datetime import datetime, timedelta, timezone
import streamlit as st

st.set_page_config(page_title="Viewer Activity – EIS", layout="centered")
st.title("Engagement Integrity Score (EIS)")
st.caption("Compute short-window integrity scores from viewer activity events")

# Inputs
video_id = st.text_input("Video ID (videos.id)", value=os.getenv("DEMO_VIDEO_ID", "10"))
minutes = st.slider("Window (minutes)", 1, 60, 5)
use_sem = st.toggle("Semantics-lite bonus (≤2 pts)", value=False)

col1, col2 = st.columns(2)
with col1:
    if st.button("Compute latest EIS window"):
        from analyzer import analyze_window
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        with st.spinner("Analyzing events..."):
            try:
                payload = analyze_window(video_id, start, end, use_semantics=use_sem)
            except Exception as e:
                st.error(f"Failed to compute EIS: {e}")
            else:
                st.success(f"EIS: {payload['eis']:.1f}")
                with st.expander("Details"):
                    st.json(payload)
with col2:
    st.info("Schema: users.id, videos.id, event. No aggregates persisted.")
