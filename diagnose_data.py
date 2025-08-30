import os
import sys
import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from dotenv import load_dotenv

try:
    # Prefer the project helper if available for consistent auth behavior
    from supabase_conn import get_supabase_client
    _CLIENT_SRC = "supabase_conn.get_supabase_client(prefer_service=True|False)"
    def _get_client():
        # Try service role first; fall back to anon/secret if SR key missing
        try:
            return get_supabase_client(prefer_service=True)
        except Exception:
            return get_supabase_client(prefer_service=False)
except Exception:
    # Fallback: construct directly from env
    from supabase import create_client, Client  # type: ignore
    _CLIENT_SRC = "create_client(SUPABASE_URL, SR_KEY|ANON_KEY|SECRET|KEY)"
    def _get_client():  # type: ignore
        url = os.environ.get("SUPABASE_URL")
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_SECRET")
            or os.environ.get("SUPABASE_KEY")
        )
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL or API key in environment")
        return create_client(url, key)


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _safe_json(data: Any, max_items: int = 5) -> str:
    try:
        if isinstance(data, list):
            data = data[:max_items]
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        return f"<unserializable: {e}>"


def _as_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _sample_types(values: Iterable[Any], k: int = 5) -> List[str]:
    out: List[str] = []
    for i, v in enumerate(values):
        if i >= k:
            break
        t = type(v).__name__
        out.append(f"{repr(v)} ({t})")
    return out


def _batch_in(client, table: str, column: str, values: List[Any], batch_size: int = 1000) -> List[dict]:
    rows: List[dict] = []
    if not values:
        return rows
    for i in range(0, len(values), batch_size):
        chunk = values[i : i + batch_size]
        # Supabase Python client supports .in_(col, list)
        res = client.table(table).select("*").in_(column, chunk).execute()
        data = getattr(res, "data", None) or []
        rows.extend(data)
    return rows


def diagnose(video_id_arg: str) -> int:
    load_dotenv()

    _print_header("Step 1: Connectivity & Video Check")
    try:
        client = _get_client()
        print(f"Connected using {_CLIENT_SRC}")
    except Exception as e:
        print("ERROR: Failed to initialize Supabase client:", e)
        return 1

    # Try to locate the video using best-effort typing
    video_row: Optional[Dict[str, Any]] = None
    tried_values: List[Any] = []
    candidates: List[Any] = []
    # Try numeric if convertible, then the raw argument
    as_int = _as_int(video_id_arg)
    if as_int is not None:
        candidates.append(as_int)
    candidates.append(video_id_arg)

    for cand in candidates:
        tried_values.append(cand)
        try:
            res = client.table("videos").select("*").eq("id", cand).limit(1).execute()
            data = getattr(res, "data", None) or []
            if data:
                video_row = data[0]
                break
        except Exception as e:
            print(f"Warning: query videos.id = {cand!r} failed: {e}")

    if not video_row:
        print("ERROR: Video not found in 'videos' table.")
        print("Tried filters:", ", ".join(repr(v) for v in tried_values))
        return 2

    canonical_vid = video_row.get("id", video_id_arg)
    print("Found video:")
    print(_safe_json(video_row, max_items=5))

    _print_header("Step 2: Event Analysis")
    events: List[Dict[str, Any]] = []
    try:
        res = client.table("event").select("*").eq("video_id", canonical_vid).execute()
        events = getattr(res, "data", None) or []
    except Exception as e:
        print("ERROR: Failed to fetch events:", e)
        return 3

    total_events = len(events)
    print(f"Total events for video {canonical_vid!r}: {total_events}")

    unique_user_ids: List[Any] = []
    if events:
        uids: List[Any] = [e.get("user_id") for e in events if e.get("user_id") is not None]
        # preserve order while deduping
        seen: Set[str] = set()
        for uid in uids:
            key = json.dumps(uid, default=str)
            if key not in seen:
                seen.add(key)
                unique_user_ids.append(uid)

    print(f"Unique user IDs referenced by events: {len(unique_user_ids)}")
    if unique_user_ids:
        samples = _sample_types(unique_user_ids, k=5)
        print("Sample user IDs (value and type):")
        for s in samples:
            print("  -", s)
    else:
        print("No user IDs present in events for this video.")

    _print_header("Step 3: User Table Analysis")
    matching_users: List[Dict[str, Any]] = []
    secondary_users: List[Dict[str, Any]] = []
    try:
        # Primary: users.id IN unique_user_ids
        if unique_user_ids:
            matching_users = _batch_in(client, "users", "id", unique_user_ids)
    except Exception as e:
        print("Warning: users.id IN (...) query failed:", e)

    # Secondary probe (not required, but helpful for diagnosis): try users.user_id
    try:
        if unique_user_ids and not matching_users:
            secondary_users = _batch_in(client, "users", "user_id", unique_user_ids)
    except Exception as e:
        # Non-fatal if users.user_id does not exist
        pass

    print(f"Matching users found by users.id: {len(matching_users)}")
    if secondary_users:
        print(f"Note: Matches found by users.user_id: {len(secondary_users)} (possible schema variant)")

    _print_header("Step 4: Root Cause Diagnosis & Report")
    # Conditions A-D
    if total_events == 0:
        print("Conclusion: No Events Found.")
        print("There are no event rows for this video. Upstream ingestion or video_id reference is likely missing.")
    else:
        unique_count = len(unique_user_ids)
        found_count = len(matching_users)
        if unique_count == 0:
            print("Conclusion: Events have no user_id.")
            print("Events exist, but none include user_id. Verify event ingestion populates user_id.")
        elif found_count == 0:
            print("Conclusion: Total Mismatch / Foreign Key Failure.")
            print("Events reference user IDs, but zero users matched on users.id.")
        elif found_count == unique_count:
            print("Conclusion: Perfect Match.")
            print("All event user IDs exist in users.id. Joins should succeed.")
        else:
            missing = unique_count - found_count
            print("Conclusion: Partial Mismatch.")
            print(f"Found {found_count} of {unique_count} referenced users; {missing} orphaned.")

    # Condition E: Potential data type mismatch
    # Compare sample types from event.user_id and users.id
    def _first_non_none(vals: Iterable[Any]) -> Optional[Any]:
        for v in vals:
            if v is not None:
                return v
        return None

    sample_event_uid = _first_non_none([e.get("user_id") for e in events])
    sample_user_id = _first_non_none([u.get("id") for u in matching_users])
    if sample_event_uid is not None and (sample_user_id is not None or not matching_users):
        ev_type = type(sample_event_uid).__name__
        us_type = type(sample_user_id).__name__ if sample_user_id is not None else "<no match>"
        warn = False
        if sample_user_id is not None:
            warn = ev_type != us_type
        else:
            # No matches: if event user_id looks numeric-as-string and users likely int, or vice versa
            # Offer a generic warning about type/format mismatch.
            warn = True
        if warn:
            print("\nWARNING: Potential Data Type or Format Mismatch detected.")
            print(f"- Sample event.user_id: {repr(sample_event_uid)} (type: {ev_type})")
            if sample_user_id is not None:
                print(f"- Sample users.id: {repr(sample_user_id)} (type: {us_type})")
            else:
                print("- Sample users.id: <no matching rows found>")
            print("This often indicates a join issue (e.g., string vs int, UUID vs int).")
            if secondary_users:
                print("Note: users.user_id matched while users.id did not. The schema may use users.user_id as the PK/foreign key in events.")

    _print_header("Step 5: Sample Data Dump (first 5 each)")
    print("Events sample:")
    print(_safe_json(events, max_items=5))
    print("\nMatching users sample (by users.id):")
    print(_safe_json(matching_users, max_items=5))
    if secondary_users:
        print("\nSecondary users sample (by users.user_id):")
        print(_safe_json(secondary_users, max_items=5))

    # Return non-zero if a likely mismatch was found
    if total_events > 0 and len(unique_user_ids) > 0 and len(matching_users) == 0:
        return 10  # strong indicator of mismatch
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python diagnose_data.py <VIDEO_ID>")
        return 64
    video_id = argv[1]
    try:
        return diagnose(video_id)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
