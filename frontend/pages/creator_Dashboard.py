import os
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env file
load_dotenv()

st.set_page_config(page_title="Creator Dashboard", page_icon="📊", layout="wide")

# Supabase initialization
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Create a Supabase client instance (with an authentication check later)
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Failed to connect to Supabase: {e}")
    supabase = None

st.title("Creator Dashboard")

# --- Auth Gate ---
user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to view your dashboard.")
    st.stop()

st.success(f"Welcome back, {user.email or 'Creator'}!")


@st.cache_data(ttl=3600)
def get_creator_data(user_id):
    """
    Fetches video metadata and analytics from Supabase for the given user.
    """
    if not supabase:
        st.warning("Supabase client is not initialized. Using dummy data.")
        # Return dummy data if Supabase connection fails
        return {
            "videos": pd.DataFrame({
                "id": [1, 2, 3],
                "filename": ["Video 1.mp4", "Video 2.mov", "Video 3.webm"],
                "created_at": pd.to_datetime(["2025-08-01", "2025-08-10", "2025-08-15"]),
                "duration_seconds": [35.2, 58.1, 42.5],
                "views": [15000, 23000, 9500],
                "likes": [850, 1500, 600],
                "shares": [50, 85, 30],
                "comments": [30, 65, 20],
                "engagement_rate": [0.06, 0.07, 0.08],
                "creator_score": [75, 88, 81],
            }),
            "creator_score_history": pd.DataFrame({
                "date": pd.to_datetime(["2025-08-01", "2025-08-05", "2025-08-10", "2025-08-15"]),
                "score": [70, 75, 80, 85]
            })
        }

    try:
        # Example of fetching data from Supabase
        # `creator_id` should be the user's ID
        response = supabase.table("videos").select("*").eq("creator_id", user_id).execute()
        videos_df = pd.DataFrame(response.data)

        # Hypothetical function to get score history
        # response_score = supabase.table("creator_scores").select("*").eq("creator_id", user_id).order("date").execute()
        # score_history_df = pd.DataFrame(response_score.data)
        
        # Replace with real data from your database
        return {
            "videos": videos_df,
            # "creator_score_history": score_history_df
        }

    except Exception as e:
        st.error(f"Error fetching data from Supabase: {e}")
        return None # or fall back to dummy data

# Fetch and load data
user_id = getattr(user, "id", None) or getattr(user, "user", {}).get("id")
data = get_creator_data(user_id)

if not data:
    st.warning("No data available for this creator. Please try again later.")
    st.stop()

videos_df = data["videos"]
# score_history_df = data["creator_score_history"]


# --- Dashboard Layout ---
st.header("Key Performance Indicators")

if not videos_df.empty:
    total_videos = len(videos_df)
    total_views = videos_df['views'].sum()
    avg_score = videos_df['creator_score'].mean()
    total_engagement = videos_df['likes'].sum() + videos_df['comments'].sum() + videos_df['shares'].sum()
    
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(label="Total Videos", value=total_videos)
    with col2:
        st.metric(label="Total Views", value=f"{total_views:,}")
    with col3:
        st.metric(label="Average Creator Score", value=f"{avg_score:.1f}")
    with col4:
        st.metric(label="Total Engagement", value=f"{total_engagement:,}")
else:
    st.info("No videos uploaded yet. Upload your first video to see your stats!")
    st.stop()


# --- Creator Score Trend ---
st.subheader("Your Progress Over Time")
# A placeholder for a real-time graph
st.line_chart(
    data=pd.DataFrame({
        "date": pd.to_datetime(["2025-08-01", "2025-08-05", "2025-08-10", "2025-08-15"]),
        "Creator Score": [70, 75, 80, 85]
    }).set_index('date')
)
st.caption("This chart shows your Creator Score, a metric based on engagement, views, and consistency.")

# --- Video Insights Table ---
st.subheader("Your Video Portfolio")

# Display an interactive table of all videos
st.dataframe(
    videos_df[[
        'filename', 'created_at', 'duration_seconds', 'views', 'likes', 
        'comments', 'shares', 'engagement_rate', 'creator_score'
    ]].sort_values('created_at', ascending=False),
    use_container_width=True,
    column_config={
        "filename": st.column_config.Column("Video Title", help="The name of the video file."),
        "created_at": st.column_config.DatetimeColumn("Upload Date", help="When the video was uploaded."),
        "duration_seconds": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
        "views": st.column_config.NumberColumn("Views", format="%d"),
        "likes": st.column_config.NumberColumn("Likes", format="%d"),
        "comments": st.column_config.NumberColumn("Comments", format="%d"),
        "shares": st.column_config.NumberColumn("Shares", format="%d"),
        "engagement_rate": st.column_config.ProgressColumn("Engagement Rate", format="%.2f%%", min_value=0, max_value=1),
        "creator_score": st.column_config.NumberColumn("Score", format="%.1f")
    }
)

# --- Video Deep Dive Section ---
st.subheader("Video Deep Dive")

# Create a selectbox with video filenames
selected_video_name = st.selectbox(
    "Select a video to see detailed analytics:",
    options=videos_df['filename'].unique(),
    index=0
)

if selected_video_name:
    selected_video_data = videos_df[videos_df['filename'] == selected_video_name].iloc[0]

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Views", f"{selected_video_data['views']:,}")
    with col2:
        st.metric("Engagement Rate", f"{selected_video_data['engagement_rate']:.2%}")

    st.write("---")

    st.subheader("Detailed Breakdown")
    st.metric("Likes", f"{selected_video_data['likes']:,}")
    st.metric("Comments", f"{selected_video_data['comments']:,}")
    st.metric("Shares", f"{selected_video_data['shares']:,}")
    st.metric("Creator Score", f"{selected_video_data['creator_score']:.1f}")

    # You could add a video player here if you have a way to access the file URL
    # st.video(f"path_to_video/{selected_video_name}")

st.write("---")
