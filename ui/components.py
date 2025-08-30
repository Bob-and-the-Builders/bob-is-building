from typing import Optional

import streamlit as st


def display_eis_gauge(score: float, title: str = "Engagement Integrity Score") -> None:
    """Render a 0-100 gauge with red/yellow/green zones."""
    s = max(0.0, min(100.0, float(score)))
    # Lazy import to avoid hard dependency when page isn't used
    import plotly.graph_objects as go
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=s,
            number={"suffix": " / 100"},
            title={"text": title},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#1f77b4"},
                "steps": [
                    {"range": [0, 50], "color": "#f8d7da"},    # red-ish
                    {"range": [50, 75], "color": "#fff3cd"},  # yellow-ish
                    {"range": [75, 100], "color": "#d4edda"}, # green-ish
                ],
            },
        )
    )
    st.plotly_chart(fig, use_container_width=True)


def display_metric_card(title: str, value: str, help_text: Optional[str] = None) -> None:
    """Wrapper around st.metric for consistency."""
    st.metric(label=title, value=value, help=help_text)


def display_anomaly_card(
    title: str,
    score: float,
    explanation: str,
    recommendation: str,
    details: str,
    severity: str = "warning",
) -> None:
    """Render a card-like anomaly diagnostic with score, context and guidance.

    Parameters
    ----------
    title: Short title for the anomaly.
    score: Numeric score (0-100) for the metric.
    explanation: Brief description of what the signal means.
    recommendation: Actionable next steps to resolve/improve.
    details: Additional context shown inside an expander.
    severity: "alert" -> red icon; "warning" -> yellow icon.
    """
    icon = "🔴" if severity == "alert" else "🟡"
    with st.container(border=True):
        st.write(f"### {icon} {title}")
        st.metric(label="Score", value=f"{float(score):.1f} / 100")
        st.write(explanation)
        st.markdown("**Recommended Action:**")
        st.write(recommendation)
        with st.expander("View Details"):
            st.write(details)
