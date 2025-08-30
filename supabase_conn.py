from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()


def get_supabase_client(prefer_service: bool = False) -> Client:
    """Create a Supabase client.

    - Set prefer_service=True for server-side usage (service role key).
    - Defaults to anon key for client-side safe reads.
    """
    url = os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if prefer_service
        else (os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SECRET"))
    )
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or API key in environment")
    return create_client(url, key)


class SupabaseDB:
    def __init__(self):
        self.SUPABASE_URL = os.environ["SUPABASE_URL"]
        self.SUPABASE_SECRET = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get(
            "SUPABASE_SECRET"
        )
        self.client = create_client(self.SUPABASE_URL, self.SUPABASE_SECRET)

    def get_table(self, table: str):
        """Fetch all rows from a table."""
        return self.client.table(table).select("*").execute().data

    def insert(self, table: str, row: dict):
        """Insert a row into a table."""
        return self.client.table(table).insert(row).execute().data

    def get_client(self) -> Client:
        return self.client
