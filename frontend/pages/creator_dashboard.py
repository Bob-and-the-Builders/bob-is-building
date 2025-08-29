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

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Failed to connect to Supabase: {e}")
    supabase = None

st.title("Creator Dashboard")

user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to upload a video.")
    st.stop()


def get_creator_id_from_email(email: str) -> int | None:
    """SELECT user_id FROM user_info WHERE email = <email>"""
    if not email:
        return None
    try:
        res = supabase.table("user_info").select("user_id").eq("email", email).single().execute()
        if res and getattr(res, "data", None):
            return res.data.get("user_id")
    except Exception as e:
        st.warning(f"Could not resolve creator_id from user_info: {e}")
    return None




@st.cache_data(ttl=600)
def get_creator_data(user_id: int):
    """
    CHANGE 2: This function is now simplified for the simulation.
    It takes an integer user_id and uses it directly.
    """
    if not supabase:
        st.warning("Supabase client is not initialized.")
        return None

    try:
        # Fetch the creator's trust score using the integer ID.
        user_response = supabase.table("users").select("creator_trust_score", "kyc_level").eq("id", user_id).single().execute()
        if user_response.data:
            creator_score = user_response.data.get('creator_trust_score', 0)
            kyc_level = user_response.data.get('kyc_level', 0) # Default to 0 if not found
        else:
            creator_score = 0
            kyc_level = 0
        # Fetch all videos for the given creator using the integer ID directly.
        videos_response = supabase.table("videos").select("*").eq("creator_id", user_id).execute()
        
        if not videos_response.data:
            return {"videos": pd.DataFrame(), "creator_score": creator_score}
            
        videos_df = pd.DataFrame(videos_response.data)

        video_ids = videos_df['id'].tolist()

        # Fetch all events for those videos
        events_response = supabase.table("event").select("video_id, event_type").in_("video_id", video_ids).execute()
        events_df = pd.DataFrame(events_response.data)

        # Aggregate the event data (this logic remains the same)
        if not events_df.empty:
            engagement_df = events_df.pivot_table(index='video_id', columns='event_type', aggfunc='size', fill_value=0)
            expected_cols = ['view', 'like', 'comment', 'share']
            for col in expected_cols:
                if col not in engagement_df.columns:
                    engagement_df[col] = 0
            
            engagement_df.rename(columns={'view': 'views', 'like': 'likes', 'comment': 'comments', 'share': 'shares'}, inplace=True)
            videos_df = pd.merge(videos_df, engagement_df, left_on='id', right_on='video_id', how='left')
            videos_df[['views', 'likes', 'comments', 'shares']] = videos_df[['views', 'likes', 'comments', 'shares']].fillna(0).astype(int)
        else:
            videos_df['views'] = 0
            videos_df['likes'] = 0
            videos_df['comments'] = 0
            videos_df['shares'] = 0

        # Calculate Engagement Rate
        videos_df['engagement_rate'] = np.where(videos_df['views'] > 0, ((videos_df['likes'] + videos_df['comments'] + videos_df['shares']) / videos_df['views']) * 100, 0)
        videos_df['creator_score'] = creator_score

        return {"videos": videos_df, "creator_score": creator_score, "kyc_level": kyc_level}

    except Exception as e:
        st.error(f"Error fetching data from Supabase: {e}")
        return None


# Fetch and load data for the current user
user_id = get_creator_id_from_email(getattr(user, "email", None))
data = get_creator_data(user_id)

if not data:
    st.warning("Could not load creator data. Please try again later.")
    st.stop()

videos_df = data["videos"]
creator_score = data["creator_score"]
kyc_level = data["kyc_level"]

# --- Dashboard Layout ---
st.header("Key Performance Indicators")

if not videos_df.empty:
    total_videos = len(videos_df)
    total_views = videos_df['views'].sum()
    total_engagement = videos_df['likes'].sum() + videos_df['comments'].sum() + videos_df['shares'].sum()
    
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(label="Total Videos", value=total_videos)
    with col2:
        st.metric(label="Total Views", value=f"{int(total_views):,}")
    with col3:
        st.metric(label="Current Creator Score", value=f"{creator_score:.1f}")
    with col4:
        st.metric(label="KYC Level", value=f"{int(kyc_level):,}")
    with col5:
        st.metric(label="Total Engagement", value=f"{int(total_engagement):,}")
else:
    st.info("This user has no videos uploaded yet.")
    st.stop()


st.subheader("Your Progress Over Time")
st.line_chart(
    data=pd.DataFrame({
        "date": pd.to_datetime(["2025-08-01", "2025-08-05", "2025-08-10", "2025-08-15"]),
        "Creator Score": [70, 75, 80, 85]
    }).set_index('date')
)
st.caption("This chart shows your Creator Score, a metric based on engagement, views, and consistency.")

st.subheader("Your Video Portfolio")

st.dataframe(
    videos_df[[
        'title', 'created_at', 'duration_s', 'views', 'likes', 
        'comments', 'shares', 'engagement_rate', 'creator_score'
    ]].sort_values('created_at', ascending=False),
    use_container_width=True,
    column_config={
        "title": st.column_config.Column("Video Title", help="The title of your video."),
        "created_at": st.column_config.DatetimeColumn("Upload Date", help="When the video was uploaded."),
        "duration_s": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
        "views": st.column_config.NumberColumn("Views", format="%d"),
        "likes": st.column_config.NumberColumn("Likes", format="%d"),
        "comments": st.column_config.NumberColumn("Comments", format="%d"),
        "shares": st.column_config.NumberColumn("Shares", format="%d"),
        "engagement_rate": st.column_config.ProgressColumn("Engagement Rate", format="%.2f%%", min_value=0, max_value=videos_df['engagement_rate'].max() if not videos_df.empty else 1),
        "creator_score": st.column_config.NumberColumn("Your Score", help="Your overall creator score at the time of viewing.", format="%.1f")
    }
)

st.subheader("Video Deep Dive")
selected_video_title = st.selectbox(
    "Select a video to see detailed analytics:",
    options=videos_df['title'].unique(),
    index=0
)
if selected_video_title:
    selected_video_data = videos_df[videos_df['title'] == selected_video_title].iloc[0]
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Views", f"{selected_video_data['views']:,}")
    with col2:
        st.metric("Engagement Rate", f"{selected_video_data['engagement_rate']:.2f}%")

    st.write("---")
    st.subheader("Detailed Breakdown")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Likes", f"{selected_video_data['likes']:,}")
    with col2:
        st.metric("Comments", f"{selected_video_data['comments']:,}")
    with col3:
        st.metric("Shares", f"{selected_video_data['shares']:,}")
    with col4:
        st.metric("Your Score", f"{selected_video_data['creator_score']:.1f}")
st.write("---")