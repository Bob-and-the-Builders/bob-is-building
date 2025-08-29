import os
import tempfile
from datetime import datetime

import streamlit as st
from supabase import Client

# Optional: moviepy for metadata extraction
from moviepy import VideoFileClip

st.set_page_config(page_title="Upload Video", page_icon="📹")

supabase: Client = st.session_state.get("supabase")

st.title("📹 Upload a Video")

# Auth gate
user = st.session_state.get("user")
if not user:
    st.info("Please sign in on the main page to upload a video.")
    st.stop()
else:
    st.info("You are logged in as: {}".format(user.email))

# Resolve creator_id via user_info
creator_id_lookup = st.session_state.get("creator_id")

uploaded_file = st.file_uploader(
    "Choose a video file",
    type=["mp4", "mov", "avi", "mkv", "webm"],
    accept_multiple_files=False,
    help="Metadata and associated information will be extracted from the video."
)

status = st.empty()

if uploaded_file is not None:
    # Persist to a temporary file to allow ffmpeg-based tools to inspect
    suffix = os.path.splitext(uploaded_file.name)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        status.info("Extracting metadata…")

        # Default metadata (for optional future use)
        metadata = {
            "creator_id": creator_id_lookup,
            "filename": uploaded_file.name,
            "filesize": uploaded_file.size,
            "mime_type": uploaded_file.type,
            "duration_seconds": None,
            "fps": None,
            "width": None,
            "height": None,
            "has_audio": None,
            "audio_fps": None,
            "codec": None,
            "created_at": datetime.utcnow().isoformat(),
        }

        # Extract with MoviePy
        try:
            clip = VideoFileClip(tmp_path)
            metadata.update({
                "duration_seconds": float(clip.duration) if clip.duration else None,
                "fps": float(clip.fps) if getattr(clip, "fps", None) else None,
                "width": int(clip.w) if getattr(clip, "w", None) else None,
                "height": int(clip.h) if getattr(clip, "h", None) else None,
                "has_audio": clip.audio is not None,
                "audio_fps": float(clip.audio.fps) if clip.audio and getattr(clip.audio, "fps", None) else None,
            })
            # Ensure resources are freed
            clip.reader.close()
            if clip.audio:
                try:
                    clip.audio.reader.close_proc()
                except Exception:
                    pass
            clip.close()
        except Exception as e:
            st.warning(f"Couldn't parse video with MoviePy: {e}")

        # Optional: try to get codec using ffprobe if available
        try:
            import subprocess
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
                tmp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            codec_name = result.stdout.strip() if result.returncode == 0 else None
            if codec_name:
                metadata["codec"] = codec_name
        except Exception:
            # ffprobe not available; skip codec
            pass

        # Map to your videos schema and insert
        # Schema: id (auto), created_at (timestamptz), creator_id (int8), title (text), duration_s (int)
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        title = os.path.splitext(uploaded_file.name)[0]
        duration_s = int(round(metadata["duration_seconds"])) if metadata["duration_seconds"] else None

        video_row = {
            "created_at": created_at,
            "creator_id": creator_id_lookup,
            "title": title,
            "duration_s": duration_s,
        }

        status.info("Saving to your TikTok videos…")
        try:
            # Insert first (no select chaining in supabase-py)
            insert_resp = supabase.table("videos").insert(video_row).execute()

            # Try to show the inserted row; fall back to the payload if needed
            saved_row = insert_resp.data[0] if getattr(insert_resp, "data", None) else None

            # Optionally refetch with specific columns if we have an id
            row_to_show = saved_row or video_row
            if saved_row and "id" in saved_row:
                try:
                    detail = (
                        supabase.table("videos")
                        .select("id, created_at, creator_id, title, duration_s")
                        .eq("id", saved_row["id"])
                        .single()
                        .execute()
                    )
                    if getattr(detail, "data", None):
                        row_to_show = detail.data
                except Exception:
                    pass

            status.success("Video saved to database!")
            with st.expander("Saved row", expanded=True):
                st.json(row_to_show)
        except Exception as e:
            status.error(f"Failed to upload video to TikTok: {e}")
    finally:
        # Remove temp file to discard the video
        try:
            os.remove(tmp_path)
        except Exception:
            pass

else:
    st.caption("Accepted formats: mp4, mov, avi, mkv, webm.")
