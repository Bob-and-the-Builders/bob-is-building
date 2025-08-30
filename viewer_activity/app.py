import os
from datetime import datetime, timedelta, timezone
import streamlit as st
from supabase_manager import client

st.set_page_config(page_title="Viewer Activity – EIS", layout="centered")
st.title("Engagement Integrity Score (EIS)")
st.caption("Compute short-window integrity scores from viewer activity events")

# Inputs
video_id = st.text_input("Video ID (videos.id)", value=os.getenv("DEMO_VIDEO_ID", "10"))
minutes = st.slider("Window (minutes)", 1, 60, 5)
 

col1, col2 = st.columns(2)
with col1:
    if st.button("Compute latest EIS window"):
        from analyzer import analyze_window
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        with st.spinner("Analyzing events..."):
            try:
                payload = analyze_window(video_id, start, end)
            except Exception as e:
                st.error(f"Failed to compute EIS: {e}")
            else:
                st.success(f"EIS: {payload['eis']:.1f}")
                with st.expander("Details"):
                    st.json(payload)
                # EIS trend chart (last ~20 aggregates)
                try:
                    agg = (
                        client.table("video_aggregates")
                        .select("window_end,eis")
                        .eq("video_id", int(video_id))
                        .order("window_end", desc=False)
                        .limit(20)
                        .execute()
                        .data
                        or []
                    )
                    if agg:
                        st.subheader("EIS Trend (recent windows)")
                        st.vega_lite_chart(
                            {
                                "data": agg,
                                "mark": {"type": "line", "point": True},
                                "encoding": {
                                    "x": {"field": "window_end", "type": "temporal", "title": "Window End"},
                                    "y": {"field": "eis", "type": "quantitative", "title": "EIS"},
                                },
                            },
                            use_container_width=True,
                        )
                except Exception as e:
                    st.info(f"No aggregates yet or failed to load trend: {e}")
with col2:
    st.info(
        "Server-only keys loaded via dotenv. Aggregates persisted to video_aggregates and videos.eis_current is updated."
    )
