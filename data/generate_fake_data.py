import argparse
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from faker import Faker
from dotenv import load_dotenv

"""
Fake data generator for the TechJam ERD while preserving foreign keys.

Tables (as used below):
  - users(id, created_at, is_creator, likely_bot, kyc_level,
          creator_trust_score, viewer_trust_score, user_info_id, current_balance)
  - user_info(id, first_name, last_name, date_of_birth, nationality,
              address, phone, email, user_id)
  - videos(id, created_at, creator_id, title, duration_s)
  - event(event_id, video_id, user_id, event_type, ts, device_id, ip_hash)
  - transactions(id, created_at, recipient, amount_cents, status, payment_type)

Two modes:
  1) Offline (default): writes JSON files under data/ with consistent IDs.
  2) Supabase insert (--insert): inserts rows in correct order and writes JSON copies.
     Requires env: SUPABASE_URL and SUPABASE_ANON_KEY (or service role).
"""


try:
    # Lazy import: only needed for --insert
    from supabase import create_client, Client  # type: ignore
except Exception:  # pragma: no cover
    create_client = None
    Client = None


fake = Faker()
random.seed(42)
Faker.seed(42)
load_dotenv()


# -----------------------
# Data model containers
# -----------------------

@dataclass
class Document:
    id: int
    full_name: str
    document_type: str
    document_number: str
    issued_date: str
    expiry_date: str
    issuing_country: str
    user_id: int
    submit_date: str

@dataclass
class User:
    id: int
    created_at: str
    is_creator: bool
    likely_bot: bool
    kyc_level: int
    creator_trust_score: Optional[int]
    viewer_trust_score: int
    user_info_id: Optional[int]
    current_balance: int  # cents


@dataclass
class UserInfo:
    id: int
    first_name: str
    last_name: str
    date_of_birth: str
    nationality: str
    address: str
    phone: str
    email: str
    user_id: int


@dataclass
class Video:
    id: int
    created_at: str
    creator_id: int
    title: str
    duration_s: int


@dataclass
class Event:
    event_id: int
    video_id: int
    user_id: int
    event_type: str
    ts: str
    device_id: str
    ip_hash: str


@dataclass
class Transaction:
    id: int
    created_at: str
    recipient: int
    amount_cents: int
    status: str
    payment_type: str


# -----------------------
# Generation functions
# -----------------------

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def gen_users(n_users: int, creator_ratio: float = 0.35) -> List[User]:
    now = datetime.utcnow()
    users: List[User] = []

    for i in range(1, n_users + 1):
        created_at = now - timedelta(days=random.randint(0, 120), hours=random.randint(0, 23))
        is_creator = random.random() < creator_ratio
        likely_bot = random.random() < 0.1
        kyc_level = random.choice([0, 1, 2, 3])
        creator_trust = random.randint(55, 100) if is_creator else None
        viewer_trust = random.randint(40, 100)

        # Simple balance model (in cents):
        # - bots: near zero
        # - creators: can hold larger balances
        # - viewers: small balances
        if likely_bot:
            balance = 0
        elif is_creator:
            balance = random.randint(0, 500_000)  # up to $3,000
        else:
            balance = 0

        users.append(
            User(
                id=i,
                created_at=iso(created_at),
                is_creator=is_creator,
                likely_bot=likely_bot,
                kyc_level=kyc_level,
                creator_trust_score=creator_trust,
                viewer_trust_score=viewer_trust,
                user_info_id=None,  # backfilled after user_info is generated
                current_balance=balance,
            )
        )
    return users


def gen_documents(users: List[UserInfo], min_per_user=1, max_per_user=3) -> List[Document]:
    docs: List[Document] = []
    doc_id = 1
    for u in users:
        count = random.randint(min_per_user, max_per_user)
        for _ in range(count):
            issued_date = fake.date_this_decade()
            
            # Use timedelta to avoid leap year issues entirely
            years_to_add = random.randint(3, 10)
            days_to_add = years_to_add * 365 + (years_to_add // 4)  # Approximate leap years
            expiry_date = issued_date + timedelta(days=days_to_add)
            
            docs.append(
                Document(
                    id=doc_id,
                    full_name=u.first_name + " " + u.last_name,
                    document_type=random.choice(["passport", "drivers_license", "national_id"]),
                    document_number=fake.bothify(text='??######'),
                    issued_date=issued_date.isoformat(),
                    expiry_date=expiry_date.isoformat(),
                    user_id=u.user_id,
                    issuing_country=fake.country(),
                    submit_date=datetime.now().isoformat()
                )
            )
            doc_id += 1
    return docs


def gen_user_info(users: List[User], reserved_emails: Optional[List[str]] = None) -> List[UserInfo]:
    infos: List[UserInfo] = []
    # Normalize and de-duplicate reserved emails (case-insensitive)
    normalized = set()
    reserved: List[str] = []
    if reserved_emails:
        for e in reserved_emails:
            e = (e or "").strip()
            low = e.lower()
            if e and low not in normalized:
                normalized.add(low)
                reserved.append(e)

    for idx, u in enumerate(users):
        dob = fake.date_between(start_date="-60y", end_date="-13y")
        email = reserved[idx] if idx < len(reserved) else fake.unique.email()
        info = UserInfo(
            id=u.id,  # mirror IDs for easy cross-reference
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            date_of_birth=str(dob),
            nationality=fake.country(),
            address=fake.address().replace("\n", ", "),
            phone=fake.phone_number(),
            email=email,
            user_id=u.id,
        )
        infos.append(info)
        u.user_info_id = info.id
    return infos


def gen_videos(users: List[User], min_per_creator=2, max_per_creator=6) -> List[Video]:
    creators = [u for u in users if u.is_creator]
    vids: List[Video] = []
    vid_id = 1
    for c in creators:
        count = random.randint(min_per_creator, max_per_creator)
        for _ in range(count):
            created_at = datetime.utcnow() - timedelta(days=random.randint(0, 90), hours=random.randint(0, 23))
            vids.append(
                Video(
                    id=vid_id,
                    created_at=iso(created_at),
                    creator_id=c.id,
                    title=fake.sentence(nb_words=random.randint(2, 6)).rstrip('.'),
                    duration_s=random.randint(5, 240),
                )
            )
            vid_id += 1
    return vids


EVENT_TYPES = [
    ("view", 0.55),
    ("like", 0.18),
    ("comment", 0.10),
    ("share", 0.07),
    ("follow", 0.05),
    ("report", 0.02),
    ("pause", 0.03),
]


def weighted_choice(weights):
    r = random.random()
    upto = 0
    for item, w in weights:
        upto += w
        if r <= upto:
            return item
    return weights[-1][0]


def gen_events(users: List[User], videos: List[Video], min_per_video=60, max_per_video=250) -> List[Event]:
    events: List[Event] = []
    ev_id = 1
    user_ids = [u.id for u in users]
    for v in videos:
        n = random.randint(min_per_video, max_per_video)
        v_created = datetime.fromisoformat(v.created_at.rstrip("Z"))
        for _ in range(n):
            etype = weighted_choice(EVENT_TYPES)
            ts = v_created + timedelta(minutes=random.randint(0, 60 * 24 * 30))
            device_kind = random.choice(["ios", "android", "web"])  # simplified device markers
            ip_hash = fake.sha256(raw_output=False)
            events.append(
                Event(
                    event_id=ev_id,
                    video_id=v.id,
                    user_id=random.choice(user_ids),
                    event_type=etype,
                    ts=iso(ts),
                    device_id=f"{device_kind}-{fake.uuid4()[:8]}",
                    ip_hash=ip_hash,
                )
            )
            ev_id += 1
    return events


def gen_transactions(users: List[User], min_per_creator=2, max_per_creator=8) -> List[Transaction]:
    creators = [u for u in users if u.is_creator]
    txs: List[Transaction] = []
    tid = 1
    for c in creators:
        n = random.randint(min_per_creator, max_per_creator)
        for _ in range(n):
            created_at = datetime.utcnow() - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23))
            status = weighted_choice([
                ("completed", 0.82),
                ("pending", 0.12),
                ("failed", 0.06),
            ])
            payment_type = weighted_choice([
                ("bank_transfer", 0.45),
                ("paypal", 0.25),
                ("wallet", 0.20),
                ("card", 0.10),
            ])
            amount = random.randint(200, 25000)  # cents
            txs.append(
                Transaction(
                    id=tid,
                    created_at=iso(created_at),
                    recipient=c.id,  # FK -> users.id (we choose creators)
                    amount_cents=amount,
                    status=status,
                    payment_type=payment_type,
                )
            )
            tid += 1
    return txs


# -----------------------
# Serialization helpers
# -----------------------

def asdict_list(items: List[Any]) -> List[Dict[str, Any]]:
    return [vars(i) for i in items]


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------
# Supabase insertion path
# -----------------------

def batch(iterable, size=500):
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def insert_supabase_all(
    users: List[User],
    infos: List[UserInfo],
    videos: List[Video],
    events: List[Event],
    txs: List[Transaction],
    documents: List[Document],
):
    if create_client is None:
        raise RuntimeError("supabase package not available. Install and try again.")

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_*_KEY in environment.")

    client: Client = create_client(url, key)

    # Insert users first
    for chunk in batch(asdict_list(users), size=500):
        client.table("users").insert(chunk).execute()

    # Insert user_info next
    for chunk in batch(asdict_list(infos), size=500):
        client.table("user_info").insert(chunk).execute()

    # Optional: backfill users.user_info_id if your schema expects it
    # Not all deployments enforce this FK, but we set it if present.
    try:
        for u in users:
            client.table("users").update({"user_info_id": u.user_info_id}).eq("id", u.id).execute()
    except Exception:
        pass

    # Insert documents
    for chunk in batch(asdict_list(documents), size=500):
        client.table("documents").insert(chunk).execute()

    # Insert videos
    for chunk in batch(asdict_list(videos), size=500):
        client.table("videos").insert(chunk).execute()

    # Insert events (can be large)
    for chunk in batch(asdict_list(events), size=1000):
        client.table("event").insert(chunk).execute()

    # Insert transactions
    for chunk in batch(asdict_list(txs), size=500):
        client.table("transactions").insert(chunk).execute()


# -----------------------
# CLI
# -----------------------

def force_creators_by_email(users: List[User], infos: List[UserInfo], emails: List[str]) -> None:
    """Ensure users with these emails are creators (and have sensible creator fields)."""
    if not emails:
        return
    wanted = {e.strip().lower() for e in emails if e and e.strip()}
    id_to_user = {u.id: u for u in users}
    for inf in infos:
        if inf.email.lower() in wanted:
            u = id_to_user[inf.user_id]
            u.is_creator = True
            if u.creator_trust_score is None:
                u.creator_trust_score = random.randint(55, 100)
            if u.current_balance == 0:
                u.current_balance = random.randint(0, 900_000)  # cents


def main():
    parser = argparse.ArgumentParser(description="Generate TechJam fake data with valid foreign keys")
    parser.add_argument("--users", type=int, default=750, help="Total users to generate")
    parser.add_argument("--creator-ratio", type=float, default=0.35, help="Fraction of users that are creators")
    parser.add_argument("--min-videos", type=int, default=2, help="Min videos per creator")
    parser.add_argument("--max-videos", type=int, default=6, help="Max videos per creator")
    parser.add_argument("--min-events", type=int, default=60, help="Min events per video")
    parser.add_argument("--max-events", type=int, default=250, help="Max events per video")
    parser.add_argument("--min-tx", type=int, default=2, help="Min transactions per creator")
    parser.add_argument("--max-tx", type=int, default=8, help="Max transactions per creator")
    parser.add_argument("--insert", action="store_true", help="Also insert into Supabase (uses env vars)")
    parser.add_argument(
        "--emails",
        nargs="*",
        default=[],
        help="Optional list of emails to force-create as users (assigned to the first N users).",
    )
    parser.add_argument(
        "--creator-emails",
        nargs="*",
        default=[],
        help="Emails that must be creators (guarantees videos/transactions for them).",
    )
    args = parser.parse_args()

    users = gen_users(args.users, args.creator_ratio)
    infos = gen_user_info(users, args.emails)
    force_creators_by_email(users, infos, args.creator_emails)
    videos = gen_videos(users, args.min_videos, args.max_videos)
    events = gen_events(users, videos, args.min_events, args.max_events)
    txs = gen_transactions(users, args.min_tx, args.max_tx)
    docs = gen_documents(users.id)

    # Write JSON snapshots (offline artifacts)
    write_json("data/users.json", asdict_list(users))
    write_json("data/user_info.json", asdict_list(infos))
    write_json("data/videos.json", asdict_list(videos))
    write_json("data/events.json", asdict_list(events))
    write_json("data/transactions.json", asdict_list(txs))
    write_json("data/documents.json", asdict_list(docs))

    print(
        f"Generated: users={len(users)}, creators={sum(1 for u in users if u.is_creator)}, "
        f"videos={len(videos)}, events={len(events)}, transactions={len(txs)}, documents={len(docs)}"
    )
    if args.emails:
        for i, e in enumerate(args.emails[: len(users)]):
            print(f"Seeded user id={users[i].id} email={e}")

    if args.insert:
        insert_supabase_all(users, infos, videos, events, txs, docs)
        print("Inserted into Supabase successfully.")


if __name__ == "__main__":
    main()
