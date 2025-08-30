from __future__ import annotations

from collections import Counter
from math import log2
from typing import Any, Dict, List, Tuple


class AnalysisEngine:
    """Computes Engagement Integrity Score (EIS) from Supabase data.

    All calculations are content-agnostic and based strictly on the provided schema:
    - users(id, viewer_trust_score)
    - videos(id, creator_id, title)
    - event(video_id, user_id, event_type)
    """

    def __init__(self, supabase_client):
        self.sb = supabase_client

    # -------------------------
    # Data access helpers
    # -------------------------
    def _get_events(self, video_id: Any) -> List[Dict[str, Any]]:
        """Return events for a video with attached viewer_trust_score per user.

        Performs a two-step join in Python:
        1) Fetch all events for video_id
        2) Fetch user trust scores for distinct user_ids and attach to events
        """
        events_res = (
            self.sb.table("event")
            .select("video_id,user_id,event_type")
            .eq("video_id", video_id)
            .execute()
        )
        events: List[Dict[str, Any]] = (events_res.data or []) if events_res else []
        if not events:
            return []

        user_ids = sorted({e.get("user_id") for e in events if e.get("user_id") is not None})
        trust_by_user: Dict[Any, float] = {}
        if user_ids:
            users_res = (
                self.sb.table("users")
                .select("id,viewer_trust_score")
                .in_("id", user_ids)
                .execute()
            )
            for row in (users_res.data or []) if users_res else []:
                trust_by_user[row.get("id")] = float(row.get("viewer_trust_score") or 0.0)

        # Attach trust score to each event
        for e in events:
            e["viewer_trust_score"] = trust_by_user.get(e.get("user_id"), 0.0)
        return events

    # -------------------------
    # Scoring components
    # -------------------------
    def _score_comment_quality(self, events: List[Dict[str, Any]]) -> float:
        """Content-agnostic comment quality based on:
        - Unique commenter rate = unique commenters / total comments
        - Average viewer_trust_score among commenters
        Weighted equally, scaled 0-100.
        """
        comments = [e for e in events if (e.get("event_type") or "").lower() == "comment"]
        if not comments:
            return 0.0

        total_comments = len(comments)
        unique_commenters = len({e.get("user_id") for e in comments if e.get("user_id") is not None})
        unique_rate = (unique_commenters / total_comments) if total_comments > 0 else 0.0

        avg_trust = sum(float(e.get("viewer_trust_score") or 0.0) for e in comments) / total_comments

        score = 0.5 * (unique_rate * 100.0) + 0.5 * avg_trust
        return max(0.0, min(100.0, score))

    def _score_like_integrity(self, events: List[Dict[str, Any]]) -> float:
        """Like integrity based on:
        - Average viewer_trust_score of likers
        - Diversity of likers = unique likers / total likes
        Weighted equally, scaled 0-100.
        """
        likes = [e for e in events if (e.get("event_type") or "").lower() == "like"]
        if not likes:
            return 0.0

        total_likes = len(likes)
        unique_likers = len({e.get("user_id") for e in likes if e.get("user_id") is not None})
        diversity = (unique_likers / total_likes) if total_likes > 0 else 0.0

        avg_trust = sum(float(e.get("viewer_trust_score") or 0.0) for e in likes) / total_likes

        score = 0.5 * (diversity * 100.0) + 0.5 * avg_trust
        return max(0.0, min(100.0, score))

    def _score_report_credibility(self, events: List[Dict[str, Any]]) -> float:
        """Higher score means fewer credible reports.

        We penalize by the combination of report count and reporter trust:
        score = 100 - min(100, avg_trust * log2(1 + count))
        If there are no reports, return 100.
        """
        reports = [e for e in events if (e.get("event_type") or "").lower() == "report"]
        if not reports:
            return 100.0

        count = len(reports)
        avg_trust = sum(float(e.get("viewer_trust_score") or 0.0) for e in reports) / max(1, count)
        penalty = min(100.0, avg_trust * (log2(1 + count)))
        score = 100.0 - penalty
        return max(0.0, min(100.0, score))

    def _score_authentic_engagement(self, events: List[Dict[str, Any]]) -> float:
        """Authenticity based on diversity of event types via normalized entropy.

        H = -sum(p_i * log2 p_i). Normalize by log2(k) where k is the number
        of unique event types observed for the video. If k <= 1, return 0.
        Result scaled to 0-100.
        """
        types = [str(e.get("event_type") or "").lower() for e in events if e.get("event_type")]
        if not types:
            return 0.0

        counts = Counter(types)
        k = len(counts)
        if k <= 1:
            return 0.0

        total = sum(counts.values())
        probs = [c / total for c in counts.values()]
        entropy = -sum(p * log2(p) for p in probs if p > 0)
        max_entropy = log2(k)
        norm = entropy / max_entropy if max_entropy > 0 else 0.0
        return max(0.0, min(100.0, norm * 100.0))

    # -------------------------
    # Public API
    # -------------------------
    def calculate_eis(self, video_id) -> Dict[str, Any]:
        """Compute the Engagement Integrity Score for a video.

        Weights:
        - Authentic Engagement: 40%
        - Comment Quality:     30%
        - Like Integrity:      15%
        - Report Credibility:  15%
        """
        events = self._get_events(video_id)

        comment_quality = self._score_comment_quality(events)
        like_integrity = self._score_like_integrity(events)
        report_credibility = self._score_report_credibility(events)
        authentic_engagement = self._score_authentic_engagement(events)

        eis = (
            0.40 * authentic_engagement
            + 0.30 * comment_quality
            + 0.15 * like_integrity
            + 0.15 * report_credibility
        )

        return {
            "eis": round(float(eis), 2),
            "breakdown": {
                "authentic_engagement": round(float(authentic_engagement), 2),
                "comment_quality": round(float(comment_quality), 2),
                "like_integrity": round(float(like_integrity), 2),
                "report_credibility": round(float(report_credibility), 2),
            },
        }
