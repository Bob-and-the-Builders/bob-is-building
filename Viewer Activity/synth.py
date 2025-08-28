# synth.py (users unified)
client.table("users").upsert([
  {"user_id":"c1","roles":["viewer","creator"],"account_created_at":now - timedelta(days=800)},
  *[{"user_id":f"u{i}","roles":["viewer"],"account_created_at":now - timedelta(days=random.randint(1,1200))} for i in range(200)]
]).execute()
client.table("videos").upsert([{
  "video_id":"v1","creator_id":"c1","title":"Latte Art Tips",
  "caption":"Quick howto for latte tulips", "hashtags":["#coffee","#tutorial","#latte"],
  "duration_s":15
}]).execute()
