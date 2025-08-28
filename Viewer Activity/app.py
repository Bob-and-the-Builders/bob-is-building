# app.py (snippets)
use_sem = st.toggle("Semantics-lite bonus (≤2 pts)", value=False)

if st.button("Compute latest EIS window"):
    from analyzer import analyze_window
    end = datetime.now(timezone.utc); start = end - timedelta(minutes=5)
    payload = analyze_window(video_id, start, end, use_semantics=use_sem)
    st.success(f"EIS: {payload['eis']:.1f}")
