import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import streamlit as st

from core.supabase_client import get_supabase_client
from core.analysis_engine import AnalysisEngine
from ui.components import (
    display_eis_gauge,
    display_metric_card,
    display_anomaly_card,
)


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

        anomalies = []

        # Authentic Engagement
        if ae_val < 50:
            anomalies.append(
                {
                    "title": "Low Authentic Engagement",
                    "score": ae_val,
                    "explanation": (
                        "Engagement appears concentrated in fewer interaction types, suggesting the content may not be broadly resonating."
                    ),
                    "recommendation": (
                        "Experiment with stronger hooks, clearer CTAs, and varied formats (e.g., questions, polls) to encourage a mix of views, likes, and comments."
                    ),
                    "details": (
                        f"Authentic Engagement score is {ae_val:.1f} (threshold 50). Review distribution across views, likes, comments, and shares to spot concentration or drop-offs."
                    ),
                    "severity": "warning",
                }
            )

        # Comment Quality
        if cq_val < 50:
            anomalies.append(
                {
                    "title": "Low Comment Quality",
                    "score": cq_val,
                    "explanation": (
                        "Comments suggest limited unique participation and/or lower average commenter trust (VTS)."
                    ),
                    "recommendation": (
                        "Prompt specific, meaningful replies; moderate low-effort or spammy comments; and engage top commenters to lift quality and diversity."
                    ),
                    "details": (
                        f"Comment Quality score is {cq_val:.1f} (threshold 50). Consider unique commenters, their trust (VTS), and repetition or spam indicators."
                    ),
                    "severity": "warning",
                }
            )

        # Like Integrity
        if li_val < 50:
            anomalies.append(
                {
                    "title": "Low Like Integrity",
                    "score": li_val,
                    "explanation": (
                        "Likes may be clustered within a small or lower-trust cohort, which can indicate inauthentic amplification."
                    ),
                    "recommendation": (
                        "Broaden audience reach and avoid tactics that incentivize low-quality likes; focus on organic discovery and authentic engagement."
                    ),
                    "details": (
                        f"Like Integrity score is {li_val:.1f} (threshold 50). Inspect like-user diversity and average VTS to spot suspicious clusters."
                    ),
                    "severity": "warning",
                }
            )

        # Report Credibility (critical below 70)
        if rc_val < 70:
            # Pull rich debug info when available (from viewer_activity analyzer)
            rc_details = breakdown.get("report_cleanliness", {}) or {}
            rc_count = rc_details.get("report_count")
            rc_avg_vts = rc_details.get("avg_reporter_vts")
            rc_penalty = rc_details.get("penalty")
            rc_reporters = rc_details.get("reporters") or []
            # Show up to 3 sample reporters with VTS
            sample = ", ".join(
                [
                    f"{str(r.get('user_id'))}: {float(r.get('vts') or 0.0):.1f}"
                    for r in rc_reporters[:3]
                ]
            ) or "None"
            details_lines = [
                f"Report Credibility score is {rc_val:.1f} (threshold 70).",
                f"Reports: {rc_count if rc_count is not None else 'N/A'}",
                f"Avg reporter VTS: {rc_avg_vts:.1f}" if isinstance(rc_avg_vts, (int, float)) else "Avg reporter VTS: N/A",
                f"Penalty applied: {rc_penalty:.2f}" if isinstance(rc_penalty, (int, float)) else "Penalty applied: N/A",
                f"Sample reporters (user_id: VTS): {sample}",
            ]
            details_text = "\n".join(details_lines)

            anomalies.append(
                {
                    "title": "Elevated Report Credibility",
                    "score": rc_val,
                    "explanation": (
                        "Higher-credibility users are reporting this video, which can signal policy or community guideline concerns."
                    ),
                    "recommendation": (
                        "Review the content against policies, check community feedback, and consider edits, disclaimers, or takedown if warranted. Respond transparently if appropriate."
                    ),
                    "details": details_text,
                    "severity": "alert",
                }
            )

        if not anomalies:
            st.success("No anomalies detected. Engagement appears organic and healthy.")
        else:
            for a in anomalies:
                display_anomaly_card(
                    title=a["title"],
                    score=a["score"],
                    explanation=a["explanation"],
                    recommendation=a["recommendation"],
                    details=a["details"],
                    severity=a.get("severity", "warning"),
                )


if __name__ == "__main__":
    main()
