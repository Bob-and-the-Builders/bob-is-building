from datetime import datetime, timedelta, timezone
from typing import List
import random

from supabase_manager import client


def seed_users(n_viewers: int = 80) -> List[str]:
    now = datetime.now(timezone.utc)
    rows = []
    # creator
    rows.append(
        {
            "id": 1,
            "created_at": (now - timedelta(days=800)).isoformat(),
            "is_creator": True,
            "viewer_trust_score": 85,
        }
    )
    for i in range(n_viewers):
        rows.append(
            {
                "id": 1000 + i,
                "created_at": (now - timedelta(days=random.randint(1, 1200))).isoformat(),
                "is_creator": False,
                "viewer_trust_score": random.choice([55, 60, 65, 70, 75, 80, 85]),
            }
        )
    client.table("users").upsert(rows).execute()
    return [str(r["id"]) for r in rows]


def seed_video(video_id: int = 10, creator_id: int = 1, duration_s: int = 15) -> None:
    client.table("videos").upsert(
        [
            {
                "id": video_id,
                "creator_id": creator_id,
                "title": "Latte Art Tips",
                "duration_seconds": duration_s,
                "fps": 30,
                "width": 1080,
                "height": 1920,
                "has_audio": True,
            }
        ]
    ).execute()


def _mk_event(video_id: int, user_id: int, event_type: str, ts: datetime):
    return {
        "video_id": video_id,
        "user_id": user_id,
        "event_type": event_type,
        "ts": ts.isoformat(),
    }


def seed_events(video_id: int = 10, minutes: int = 5) -> int:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)
    viewers = [r["id"] for r in client.table("users").select("id").execute().data if r["id"] != 1]
    if not viewers:
        return 0

    events = []
    # Views for a subset of viewers
    view_sample = random.sample(viewers, k=max(1, int(0.6 * len(viewers))))
    for u in view_sample:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "view", ts))

    # Likes from subset of viewers who viewed
    like_users = random.sample(view_sample, k=max(1, int(0.3 * len(view_sample))))
    for u in like_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "like", ts))

    # Comments: include some spam/toxic for moderation
    comment_users = random.sample(view_sample, k=max(1, int(0.12 * len(view_sample))))
    for u in comment_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "comment", ts))

    # Reports: small fraction
    report_users = random.sample(view_sample, k=max(1, int(0.03 * len(view_sample))))
    for u in report_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "report", ts))

    client.table("event").insert(events).execute()
    return len(events)


def main(video_id: int = 10, minutes: int = 5) -> None:
    seed_users()
    seed_video(video_id)
    n = seed_events(video_id, minutes)
    print(f"Seeded {n} events for video {video_id} in last {minutes} minutes.")
    try:
        from analyzer import analyze_window

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        payload = analyze_window(video_id, start, end, use_semantics=True)
        print(f"EIS: {payload['eis']:.1f}")
    except Exception as e:
        print(f"Seed complete, but EIS computation failed: {e}")


if __name__ == "__main__":
    main()
