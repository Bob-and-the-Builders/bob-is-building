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
