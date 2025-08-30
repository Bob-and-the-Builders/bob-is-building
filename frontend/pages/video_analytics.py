import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import streamlit as st

from core.supabase_client import get_supabase_client
from core.analysis_engine import AnalysisEngine
from ui.components import display_eis_gauge, display_metric_card


def _get_creator_videos(sb, creator_id):
    res = (
        sb.table("videos")
        .select("id,title")
        .eq("creator_id", creator_id)
        .order("title")
        .execute()
    )
    return (res.data or []) if res else []


def _video_option_label(video_row):
    title = video_row.get("title") or "Untitled"
    vid = str(video_row.get("id") or "").split("-")[0]
    return f"{title} ({vid})"


def main():
    st.title("Video Analytics")
    st.caption("Engagement Integrity insights for your content")

    # Ensure user context
    creator_id = st.session_state.get("creator_id")
    if not creator_id:
        st.info("Please log in to view your analytics.")
        return

    # Supabase client
    sb = st.session_state.get("supabase") or get_supabase_client()

    # Fetch creator videos
    with st.spinner("Loading your videos..."):
        videos = _get_creator_videos(sb, creator_id)

    if not videos:
        st.warning("No videos found for your account.")
        return

    # Select video
    labels = [_video_option_label(v) for v in videos]
    selected_idx = st.selectbox(
        "Select a video to analyze",
        options=list(range(len(videos))),
        format_func=lambda i: labels[i],
    )
    selected_video = videos[selected_idx]

    # Compute EIS
    engine = AnalysisEngine(sb)
    with st.spinner("Computing Engagement Integrity Score..."):
        result = engine.calculate_eis(selected_video["id"])  # accepts UUID or int

    eis = float(result.get("eis", 0.0))
    breakdown = result.get("breakdown", {})
    ae_val = float(breakdown.get("authentic_engagement", 0.0))
    cq_val = float(breakdown.get("comment_quality", 0.0))
    li_val = float(breakdown.get("like_integrity", 0.0))
    rc_val = float(breakdown.get("report_credibility", 0.0))

    overview_tab, anomalies_tab = st.tabs(["Overview", "Anomaly Detection"])

    with overview_tab:
        display_eis_gauge(eis)

        # Explanations via popovers, with metric cards directly under each
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.popover("Authentic Engagement"):
                st.write(
                    "Measures how compelling the content is by rewarding a variety of interactions (views, likes, comments)."
                )
            display_metric_card("Authentic Engagement", f"{ae_val:.1f}")
        with c2:
            with st.popover("Comment Quality"):
                st.write(
                    "Reflects community health based on commenter trust (VTS) and the rate of unique participants."
                )
            display_metric_card("Comment Quality", f"{cq_val:.1f}")
        with c3:
            with st.popover("Like Integrity"):
                st.write(
                    "Evaluates authenticity of likes using user diversity and trust (VTS), helping filter out bots."
                )
            display_metric_card("Like Integrity", f"{li_val:.1f}")
        with c4:
            with st.popover("Report Credibility"):
                st.write(
                    "Higher is better: the score decreases when high-trust users report the video."
                )
            display_metric_card("Report Credibility", f"{rc_val:.1f}")

    with anomalies_tab:
        st.subheader("Signals & Warnings")
        any_flag = False

        if ae_val < 50:
            any_flag = True
            st.warning(
                "Low Authentic Engagement: interactions appear concentrated in a few event types."
            )
        if cq_val < 50:
            any_flag = True
            st.warning(
                "Low Comment Quality: limited unique commenters and/or lower average trust."
            )
        if li_val < 50:
            any_flag = True
            st.warning(
                "Low Like Integrity: likes may come from a small or lower-trust cohort."
            )
        if rc_val < 70:
            any_flag = True
            st.error(
                "Elevated Report Credibility: consider reviewing the content and community feedback."
            )

        if not any_flag:
            st.success("No anomalies detected. Engagement appears organic and healthy.")


if __name__ == "__main__":
    main()
