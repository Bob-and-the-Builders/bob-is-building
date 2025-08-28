# semantics_lite.py
from typing import List
from collections import Counter

CATS = {
  "tutorial": ["howto","guide","tips","tutorial","learn","hack"],
  "art": ["art","drawing","craft","design","edit"],
  "food": ["food","recipe","cook","coffee","latte","kitchen"],
  "gaming": ["game","gaming","minecraft","roblox","valorant"],
  "fitness": ["fit","workout","gym","yoga","run"],
  "finance": ["money","budget","finance","invest","scam"]
}

NICHE = {"art","coffee","latte","pottery","origami","woodwork"}  # tiny nudge

def classify(caption: str, hashtags: List[str]):
    text = (caption or "").lower() + " " + " ".join((h or "").lower().lstrip("#") for h in hashtags)
    hits=[]
    for cat, keys in CATS.items():
        if any(k in text for k in keys): hits.append(cat)
    return list(set(hits)) or ["general"]

def semantics_bonus(caption: str, hashtags: List[str]) -> float:
    cats = classify(caption, hashtags)
    # +1 if niche, +1 if multiple categories (diversity context)
    niche_hit = any(k in (caption or "").lower() or any(k in (h or "").lower() for h in hashtags) for k in NICHE)
    bonus = (1.0 if niche_hit else 0.0) + (1.0 if len(cats) >= 2 else 0.0)
    return float(min(2.0, bonus))
