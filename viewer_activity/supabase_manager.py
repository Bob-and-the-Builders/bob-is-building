# supabase_manager.py (patched)
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import os
from dotenv import load_dotenv

load_dotenv()

try:
    from supabase import create_client as _create_client  # type: ignore
except Exception as _e:
    _create_client = None  # type: ignore

def _make_client():
    url = os.getenv("SUPABASE_URL")
    # Prefer service role for server-side writes, fallback to anon for readonly
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SECRET")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        raise RuntimeError("Missing Supabase credentials: set SUPABASE_URL and a service/anon key env var.")
    if _create_client is None:
        raise RuntimeError("supabase package not installed. Please `pip install supabase`. ")
    return _create_client(url, key)

client = _make_client()

@dataclass
class ViewerEvent:
    # event table per diagram: event_id (int8), video_id (int8), user_id (int8), event_type (text), ts (timestamptz)
    video_id: str
    user_id: str
    event_type: str
    ts: datetime
    event_id: Optional[int] = None
    device_id: Optional[str] = None
    ip_hash: Optional[str] = None
    def to_row(self):
        d = asdict(self)
        # remove None event_id so DB can auto-generate if it’s identity/serial
        if d.get("event_id") is None:
            d.pop("event_id", None)
        return d

def insert_events(events: List[ViewerEvent]):
    """Bulk insert viewer events into `event` table.

    Raises RuntimeError with context if insertion fails.
    """
    if not events:
        return
    rows = [e.to_row() for e in events]
    try:
        client.table("event").insert(rows).execute()
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to insert events: {e}")

def fetch_events(video_id: str, start: datetime, end: datetime):
    """Fetch events for a video within [start, end). Returns a list of dicts."""
    try:
        data = (
            client.table("event")
            .select("*")
            .eq("video_id", video_id)
            .gte("ts", start.isoformat())
            .lt("ts", end.isoformat())
            .order("ts")
            .execute()
            .data
            or []
        )
        return data
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to fetch events for video {video_id}: {e}")

def upsert_aggregate(video_id: str, ws, we, payload: Dict):
    """Insert a `video_aggregates` row and update `videos.eis_current`.

    Raises RuntimeError with context if DB operations fail.
    """
    try:
        client.table("video_aggregates").insert(
            {
                "video_id": int(video_id),
                "window_start": ws.isoformat(),
                "window_end": we.isoformat(),
                "features": payload.get("features", {}),
                "comment_quality": payload.get("comment_quality"),
                "like_integrity": payload.get("like_integrity"),
                "report_credibility": payload.get("report_credibility"),
                "authentic_engagement": payload.get("authentic_engagement"),
                "eis": payload.get("eis"),
            }
        ).execute()
        client.table("videos").update(
            {
                "eis_current": payload.get("eis"),
                "eis_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", int(video_id)).execute()
    except Exception as e:  # pragma: no cover - external I/O
        raise RuntimeError(f"Failed to upsert aggregates for video {video_id}: {e}")
