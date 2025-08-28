# supabase_manager.py (patched)
from supabase import create_client
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional
import os, uuid

client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY"))

@dataclass
class ViewerEvent:
    event_id: str
    video_id: str
    user_id: str
    event_type: str
    ts: datetime
    device_id: Optional[str]=None
    ip_hash: Optional[str]=None
    metadata: Dict=None
    def to_row(self): 
        d=asdict(self); d["metadata"]=d.get("metadata") or {}; return d

def insert_events(events: List[ViewerEvent]):
    client.table("viewer_events").insert([e.to_row() for e in events]).execute()

def fetch_events(video_id: str, start: datetime, end: datetime):
    return (client.table("viewer_events").select("*")
            .eq("video_id", video_id)
            .gte("ts", start.isoformat()).lt("ts", end.isoformat())
            .order("ts").execute().data or [])

def upsert_aggregate(video_id: str, ws, we, payload: Dict):
    client.table("video_aggregates").insert({
        "video_id": video_id,
        "window_start": ws.isoformat(),
        "window_end": we.isoformat(),
        **payload
    }).execute()
    client.table("videos").update({
        "eis_current": payload["eis"],
        "eis_updated_at": datetime.utcnow().isoformat()
    }).eq("video_id", video_id).execute()
