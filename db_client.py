from supabase import create_client, Client
import os
from dotenv import load_dotenv

# Load environment variables at the top of the script
load_dotenv()

class SupabaseDB:
    def __init__(self):
        # Retrieve environment variables for the URL and public key
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_ANON_KEY")

        # Create the Supabase client and store it as a class attribute
        self.client = create_client(supabase_url, supabase_key)

    def get_table(self, table: str):
        """Fetch all rows from a table."""
        return self.client.table(table).select("*").execute().data

    def insert(self, table: str, row: dict):
        """Insert a row into a table."""
        return self.client.table(table).insert(row).execute().data

    def get_client(self) -> Client:
        """Returns the initialized Supabase client."""
        return self.client