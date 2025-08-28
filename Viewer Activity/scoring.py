# scoring.py (only function shown that changed data source)
from supabase_manager import client
from datetime import datetime

def compute_vts_row(u):
    age_days = max(0,(datetime.utcnow()-datetime.fromisoformat(u["account_created_at"]) if u.get("account_created_at") else datetime.utcnow()).days)
    ip_risk = u.get("ip_asn_risk",0)
    prior   = u.get("prior_false_report_rate",0.0)
    return float(max(0,min(100, 50 + 0.2*age_days - 15*ip_risk - 30*prior)))

def get_vts_map(user_ids):
    if not user_ids: return {}
    rows = client.table("users").select("*").in_("user_id", user_ids).execute().data or []
    return {r["user_id"]: compute_vts_row(r) for r in rows}
