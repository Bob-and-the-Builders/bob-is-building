from supabase_conn import create_client, Client
import os
from dotenv import load_dotenv
load_dotenv()

class SupabaseDB:
    def __init__(self):
        self.SUPABASE_URL = os.environ.get("SUPABASE_URL")
        self.SUPABASE_SECRET = os.environ.get("SUPABASE_SECRET")
        self.client = Client(self.SUPABASE_URL, self.SUPABASE_SECRET)

supabase_db = SupabaseDB()

response = (
    supabase_db.client.table("users").select("*").execute()
)

print(response)