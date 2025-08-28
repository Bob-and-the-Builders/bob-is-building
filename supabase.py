from supabase import create_client, Client
import os

class SupabaseDB:
    def __init__(self):
        self.SUPABASE_URL = os.environ["SUPABASE_URL"]
        self.SUPABASE_SECRET = os.environ["SUPABASE_ANON_KEY"]
        self.client = create_client(self.SUPABASE_URL, self.SUPABASE_SECRET)

    