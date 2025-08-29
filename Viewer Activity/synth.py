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
                "duration_s": duration_s,
            }
        ]
    ).execute()


def _mk_event(video_id: int, user_id: int, event_type: str, ts: datetime, device_id: str | None, ip_hash: str | None):
    row = {
        "video_id": video_id,
        "user_id": user_id,
        "event_type": event_type,
        "ts": ts.isoformat(),
    }
    if device_id:
        row["device_id"] = device_id
    if ip_hash:
        row["ip_hash"] = ip_hash
    return row


def seed_events(video_id: int = 10, minutes: int = 5) -> int:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)
    viewers = [r["id"] for r in client.table("users").select("id").execute().data if r["id"] != 1]
    if not viewers:
        return 0

    events = []
    # Assign per-user device/ip; create a small cluster to simulate abuse
    user_device = {}
    user_ip = {}
    shared_device = "dev-shared-1"
    shared_ip = "ip-shared-1"
    for u in viewers:
        if random.random() < 0.1:  # 10% of users share same device/ip (suspicious cluster)
            user_device[u] = shared_device
            user_ip[u] = shared_ip
        else:
            user_device[u] = f"dev-{u}"
            user_ip[u] = f"ip-{u}"
    # Views for a subset of viewers
    view_sample = random.sample(viewers, k=max(1, int(0.6 * len(viewers))))
    for u in view_sample:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "view", ts, user_device.get(u), user_ip.get(u)))

    # Likes from subset of viewers who viewed
    like_users = random.sample(view_sample, k=max(1, int(0.3 * len(view_sample))))
    for u in like_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "like", ts, user_device.get(u), user_ip.get(u)))

    # Comments: include some spam/toxic for moderation
    comment_users = random.sample(view_sample, k=max(1, int(0.12 * len(view_sample))))
    for u in comment_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "comment", ts, user_device.get(u), user_ip.get(u)))

    # Reports: small fraction
    report_users = random.sample(view_sample, k=max(1, int(0.03 * len(view_sample))))
    for u in report_users:
        ts = start + timedelta(seconds=random.randint(0, minutes * 60))
        events.append(_mk_event(video_id, u, "report", ts, user_device.get(u), user_ip.get(u)))

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
