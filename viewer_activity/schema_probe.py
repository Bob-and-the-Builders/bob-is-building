from supabase import create_client
from dotenv import load_dotenv
import os

TABLES = ["users", "videos", "event", "user_info", "transactions"]


def connect():
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        raise SystemExit("Missing SUPABASE_URL and service/anon key in env.")
    return create_client(url, key)


def try_meta(client):
    # Attempt pg_meta.columns if exposed
    try:
        cols = (
            client.table("pg_meta.columns")
            .select("name, table, schema")
            .in_("table", TABLES)
            .eq("schema", "public")
            .execute()
            .data
            or []
        )
        out = {}
        for c in cols:
            out.setdefault(c["table"], []).append(c["name"])
        return out
    except Exception:
        return None


def sample_keys(client, table):
    try:
        data = client.table(table).select("*").limit(1).execute().data or []
        if data:
            return sorted(list(data[0].keys()))
        # Try a few common columns to infer presence
        probe_cols = [
            "id,created_at",
            "id,title",
            "event_id,video_id,user_id,event_type,ts",
        ]
        for cols in probe_cols:
            try:
                client.table(table).select(cols).limit(0).execute()
                return cols.split(",")
            except Exception:
                continue
        return []
    except Exception:
        return []


def main():
    client = connect()
    meta = try_meta(client)
    if meta:
        print("pg_meta.columns detected. Columns by table:\n")
        for t in TABLES:
            print(f"- {t}: {sorted(meta.get(t, []))}")
    else:
        print("Falling back to sampling rows. Columns detected:\n")
        for t in TABLES:
            print(f"- {t}: {sample_keys(client, t)}")

    # Show one example row for videos and event if exists
    for t in ("videos", "event"):
        try:
            rows = client.table(t).select("*").limit(1).execute().data or []
            print(f"\nSample {t} row:")
            print(rows[0] if rows else "<none>")
        except Exception as e:
            print(f"\nSample {t} row: <error> {e}")


if __name__ == "__main__":
    main()

