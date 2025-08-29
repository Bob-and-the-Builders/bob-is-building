# supabase_manager.py (patched)
from supabase_conn import create_client
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import os

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
    return create_client(url, key)

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
    if not events:
        return
    rows = [e.to_row() for e in events]
    client.table("event").insert(rows).execute()

def fetch_events(video_id: str, start: datetime, end: datetime):
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

def upsert_aggregate(video_id: str, ws, we, payload: Dict):
    # Diagram schema has no aggregates or EIS columns; this is a no-op
    return
