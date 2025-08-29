from supabase import create_client, Client
import os
from dotenv import load_dotenv
load_dotenv()

class SupabaseDB:
    def __init__(self):
        self.SUPABASE_URL = os.environ["SUPABASE_URL"]
        self.SUPABASE_SECRET = os.environ["SUPABASE_ANON_KEY"]
        self.client = create_client(self.SUPABASE_URL, self.SUPABASE_SECRET)

    def get_table(self, table: str):
        """Fetch all rows from a table."""
        return self.client.table(table).select("*").execute().data

    def insert(self, table: str, row: dict):
        """Insert a row into a table."""
        return self.client.table(table).insert(row).execute().data

    def get_client(self) -> Client:
        return self.client