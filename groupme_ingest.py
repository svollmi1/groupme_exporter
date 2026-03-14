import argparse
import os
import time
import json
import sqlite3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta

# === Credentials via environment ===
TOKEN = os.environ.get("GROUPME_TOKEN")
GROUP_ID = os.environ.get("GROUPME_GROUP_ID")

if not TOKEN or not GROUP_ID:
    raise SystemExit(
        "Missing required env vars. Set GROUPME_TOKEN and GROUPME_GROUP_ID "
        "(e.g., via /etc/groupme.env or your shell)."
    )

# === API/DB config ===
BASE       = "https://api.groupme.com/v3"
DB_PATH    = os.path.join(os.path.dirname(__file__), "groupme.sqlite")
SCHEMA_PATH= os.path.join(os.path.dirname(__file__), "groupme_schema.sql")
PAGE_LIMIT = 100
MIN_SLEEP  = 0.25          # polite pacing between pages
MAX_RETRIES= 6             # retries inside api_get
DAEMON_DEFAULT_INTERVAL = 20  # seconds between live polls

# ---------- HTTP session with retries ----------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "groupme-ingestor/2.2 (+local)"})
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=[420, 429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

SESSION = make_session()

def api_get(path: str, params: Dict[str, Any]) -> Any:
    """
    GET with retry/backoff for:
      - HTTP 420/429/5xx (adapter Retry + loop)
      - SSL/connection/timeouts
      - Unexpected non-JSON/empty bodies (treat as empty page after retries)
    """
    params = dict(params or {})
    params["token"] = TOKEN

    backoff = 1.0
    for _ in range(MAX_RETRIES):
        try:
            r = SESSION.get(f"{BASE}{path}", params=params, timeout=(10, 60))  # (connect, read)
            if r.status_code in (420, 429) or r.status_code >= 500:
                time.sleep(backoff); backoff = min(backoff * 2, 30); continue
            ct = (r.headers.get("Content-Type") or "").lower()
            if not r.content or ("application/json" not in ct):
                time.sleep(backoff); backoff = min(backoff * 2, 30); continue
            return r.json().get("response", {})
        except (requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout,
                ValueError):
            time.sleep(backoff); backoff = min(backoff * 2, 30); continue

    # Final attempt: if still non-JSON/empty, treat as "no more messages"
    r = SESSION.get(f"{BASE}{path}", params=params, timeout=(10, 60))
    if not r.content:
        return {"messages": []}
    try:
        return r.json().get("response", {})
    except Exception:
        return {"messages": []}

# ---------- DB helpers ----------
def ensure_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

def ensure_member(conn: sqlite3.Connection,
                  user_id: Optional[str],
                  nickname: Optional[str] = None,
                  image_url: Optional[str] = None) -> None:
    if not user_id:
        return
    conn.execute(
        "INSERT OR IGNORE INTO members(user_id, nickname, image_url) VALUES (?,?,?)",
        (user_id, nickname, image_url)
    )

def upsert_group_and_members(conn: sqlite3.Connection) -> None:
    resp = api_get(f"/groups/{GROUP_ID}", {})
    conn.execute("INSERT OR REPLACE INTO groups(id, name) VALUES (?,?)",
                 (resp["id"], resp.get("name")))
    for m in resp.get("members", []):
        conn.execute(
            "INSERT OR REPLACE INTO members(user_id, nickname, image_url) VALUES (?,?,?)",
            (m["user_id"], m.get("nickname"), m.get("image_url"))
        )
        role = (m.get("roles") or [None])[0]
        conn.execute(
            "INSERT OR REPLACE INTO group_members(group_id, user_id, role) VALUES (?,?,?)",
            (GROUP_ID, m["user_id"], role)
        )
    conn.commit()

def load_checkpoint(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT before_id, ingested_count FROM ingestion_progress WHERE group_id=?",
        (GROUP_ID,)
    ).fetchone()
    return (row[0], row[1]) if row else (None, 0)

def save_checkpoint(conn: sqlite3.Connection, before_id: Optional[str], ingested: int) -> None:
    conn.execute(
        "INSERT INTO ingestion_progress(group_id, before_id, ingested_count) VALUES (?,?,?) "
        "ON CONFLICT(group_id) DO UPDATE SET before_id=excluded.before_id, ingested_count=excluded.ingested_count",
        (GROUP_ID, before_id, ingested)
    )
    conn.commit()

def insert_message(conn: sqlite3.Connection, msg: Dict[str, Any]) -> None:
    # Ensure author exists
    ensure_member(conn, msg.get("user_id"), msg.get("name"), msg.get("avatar_url"))

    conn.execute(
        "INSERT OR IGNORE INTO messages(id, group_id, created_at, user_id, name, text, source_guid, system) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            msg["id"], GROUP_ID, msg["created_at"], msg.get("user_id"),
            msg.get("name"), msg.get("text"), msg.get("source_guid"),
            1 if msg.get("system") else 0
        )
    )

    # Likes
    for uid in msg.get("favorited_by", []):
        ensure_member(conn, uid)
        conn.execute(
            "INSERT OR IGNORE INTO likes(message_id, user_id) VALUES (?,?)",
            (msg["id"], uid)
        )

    # Reactions (emoji incl. hearts; code may be blank/NULL on some clients)
    for react in (msg.get("reactions") or []):
        code = react.get("code")
        rtype = react.get("type")
        for uid in react.get("user_ids", []):
            ensure_member(conn, uid)
            conn.execute(
                "INSERT OR IGNORE INTO reactions(message_id, type, code, user_id) VALUES (?,?,?,?)",
                (msg["id"], rtype, code, uid)
            )

    # Attachments (idempotent; unique index recommended)
    for att in (msg.get("attachments") or []):
        conn.execute(
            "INSERT OR IGNORE INTO attachments(message_id, type, url, lat, lon, name, data) VALUES (?,?,?,?,?,?,?)",
            (
                msg["id"],
                att.get("type"),
                att.get("url"),
                (att.get("lat") if isinstance(att.get("lat"), (int, float)) else None),
                (att.get("lng") if isinstance(att.get("lng"), (int, float)) else None),
                att.get("name"),
                json.dumps(att, ensure_ascii=False)
            )
        )

def newest_id(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT id FROM messages ORDER BY CAST(id AS INTEGER) DESC LIMIT 1").fetchone()
    return row[0] if row else None

def current_total(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

def get_total_message_count() -> Optional[int]:
    try:
        resp = api_get(f"/groups/{GROUP_ID}/messages", {"limit": 1})
        return resp.get("count")
    except Exception:
        return None

# ---------- Sync routines ----------
def backfill(conn: sqlite3.Connection, verbose: bool = False, test_pages: Optional[int] = None) -> int:
    """Historical sync (pages backward using before_id). Returns pages processed."""
    before_id, _ = load_checkpoint(conn)
    page_count = 0
    stagnant_pages = 0
    prev_before_id = None

    while True:
        params = {"limit": PAGE_LIMIT}
        if before_id:
            params["before_id"] = before_id

        page = api_get(f"/groups/{GROUP_ID}/messages", params)
        batch: List[Dict[str, Any]] = page.get("messages", [])
        if not batch:
            if verbose: print("[backfill] empty page → done")
            break

        before_changes = conn.total_changes
        for m in batch:
            insert_message(conn, m)
        conn.commit()
        inserted_now = conn.total_changes - before_changes
        page_count += 1

        oldest = min(batch, key=lambda m: int(m["id"]))["id"]

        # progress detection
        if oldest == before_id or before_id == prev_before_id:
            stagnant_pages += 1
        else:
            stagnant_pages = 0

        prev_before_id, before_id = before_id, oldest
        save_checkpoint(conn, before_id, current_total(conn))

        if verbose:
            print(f"[backfill] page={page_count} inserted={inserted_now} oldest={oldest} total={current_total(conn)}")

        time.sleep(MIN_SLEEP)

        if test_pages and page_count >= test_pages:
            if verbose: print("[backfill] test mode page cap reached")
            break
        if stagnant_pages >= 2:
            if verbose: print("[backfill] stagnant pages → done")
            break

    return page_count

def topoff(conn: sqlite3.Connection, verbose: bool = False, head_pages: int = 3) -> int:
    """
    Head sweep: crawl the newest pages using before_id to avoid gaps from non-monotonic IDs.
    We fetch up to `head_pages` newest pages each cycle. INSERT OR IGNORE prevents dupes.
    Returns number of rows inserted (any table).
    """
    added_total = 0
    pages = 0
    before_id = None
    stagnant = 0

    while pages < head_pages:
        params = {"limit": PAGE_LIMIT}
        if before_id:
            params["before_id"] = before_id

        resp = api_get(f"/groups/{GROUP_ID}/messages", params)
        batch: List[Dict[str, Any]] = resp.get("messages", [])
        if not batch:
            if verbose: print("[topoff] empty newest page")
            break

        before = conn.total_changes
        for m in batch:
            insert_message(conn, m)
        conn.commit()
        inserted_now = conn.total_changes - before
        added_total += inserted_now

        oldest_in_page = min(batch, key=lambda m: int(m["id"]))["id"]
        before_id = oldest_in_page
        pages += 1

        if verbose:
            print(f"[topoff] page {pages}: fetched={len(batch)} inserted={inserted_now} oldest={oldest_in_page} total={current_total(conn)}")

        # if two consecutive newest pages add nothing, we’re up to date
        if inserted_now == 0:
            stagnant += 1
            if stagnant >= 2:
                if verbose: print("[topoff] two stagnant pages → up-to-date")
                break
        else:
            stagnant = 0

        time.sleep(MIN_SLEEP)

    return added_total

# ---------- Reconciliation (likes & reactions removals/edits) ----------
def _norm_code(v: Optional[str]) -> str:
    """Normalize code for comparison: treat NULL as empty string."""
    return v if isinstance(v, str) else ""

def _desired_sets_from_msg(msg: Dict[str, Any]) -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    """Build desired sets from an API message payload."""
    likes_desired: Set[str] = set(msg.get("favorited_by") or [])
    reacts_desired: Set[Tuple[str, str, str]] = set()
    for react in (msg.get("reactions") or []):
        rtype = react.get("type")
        code  = _norm_code(react.get("code"))
        for uid in (react.get("user_ids") or []):
            reacts_desired.add((rtype or "", code, uid))
    return likes_desired, reacts_desired

def _existing_sets_from_db(conn: sqlite3.Connection, message_id: str) -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    """Read existing likes & reactions for a message from DB, with normalized code for reactions."""
    cur = conn.cursor()
    likes_rows = cur.execute("SELECT user_id FROM likes WHERE message_id=?", (message_id,)).fetchall()
    likes_existing: Set[str] = {row[0] for row in likes_rows}

    react_rows = cur.execute(
        "SELECT type, COALESCE(code,''), user_id FROM reactions WHERE message_id=?",
        (message_id,)
    ).fetchall()
    reacts_existing: Set[Tuple[str, str, str]] = {(t or "", c or "", u) for (t, c, u) in react_rows}
    return likes_existing, reacts_existing

def _reconcile_one(conn: sqlite3.Connection, msg: Dict[str, Any]) -> Tuple[int, int]:
    """
    Reconcile a single message's likes & reactions to match API exactly.
    Returns (changes_applied, net_rows_changed) for diagnostics.
    """
    message_id = msg["id"]
    # Ensure the message row exists (safe)
    insert_message(conn, msg)

    likes_desired, reacts_desired = _desired_sets_from_msg(msg)
    likes_existing, reacts_existing = _existing_sets_from_db(conn, message_id)

    # Compute diffs
    likes_to_add    = likes_desired - likes_existing
    likes_to_remove = likes_existing - likes_desired

    reacts_to_add    = reacts_desired - reacts_existing
    reacts_to_remove = reacts_existing - reacts_desired

    cur = conn.cursor()

    # Apply likes deletions
    for uid in likes_to_remove:
        cur.execute("DELETE FROM likes WHERE message_id=? AND user_id=?", (message_id, uid))

    # Apply likes additions
    for uid in likes_to_add:
        cur.execute("INSERT OR IGNORE INTO likes(message_id, user_id) VALUES (?,?)", (message_id, uid))

    # Apply reaction deletions (use normalized code match)
    for (rtype, code_norm, uid) in reacts_to_remove:
        cur.execute(
            "DELETE FROM reactions WHERE message_id=? AND user_id=? AND type=? AND COALESCE(code,'')=?",
            (message_id, uid, rtype, code_norm)
        )

    # Apply reaction additions
    for (rtype, code_norm, uid) in reacts_to_add:
        # Store raw code as None if empty to match earlier inserts; using '' is also fine since we compare normalized.
        db_code = None if code_norm == "" else code_norm
        cur.execute(
            "INSERT OR IGNORE INTO reactions(message_id, type, code, user_id) VALUES (?,?,?,?)",
            (message_id, rtype, db_code, uid)
        )

    conn.commit()
    changes_applied = len(likes_to_add) + len(likes_to_remove) + len(reacts_to_add) + len(reacts_to_remove)
    # net rows changed = +adds - removes
    net = (len(likes_to_add) + len(reacts_to_add)) - (len(likes_to_remove) + len(reacts_to_remove))
    return changes_applied, net

def reconcile_head(conn: sqlite3.Connection, pages: int = 6, verbose: bool = False) -> Tuple[int, int]:
    """
    Reconcile likes/reactions for the newest `pages` pages.
    Returns (messages_processed, total_changes_applied).
    """
    processed = 0
    total_changes = 0
    before_id = None
    for p in range(pages):
        params = {"limit": PAGE_LIMIT}
        if before_id:
            params["before_id"] = before_id
        resp = api_get(f"/groups/{GROUP_ID}/messages", params)
        batch: List[Dict[str, Any]] = resp.get("messages", [])
        if not batch:
            if verbose: print(f"[reconcile] page {p+1}: empty")
            break

        # Process each message in the newest page
        for m in batch:
            changes, net = _reconcile_one(conn, m)
            processed += 1
            total_changes += changes
            if verbose and changes:
                print(f"[reconcile] msg={m['id']} changes={changes} (net {net:+})")

        # advance to next page (older)
        before_id = min(batch, key=lambda m: int(m["id"]))["id"]
        if verbose:
            print(f"[reconcile] page {p+1}: processed={len(batch)}; next before_id={before_id}")
        time.sleep(MIN_SLEEP)

    if verbose:
        print(f"[reconcile] done: messages_processed={processed} total_changes={total_changes}")
    return processed, total_changes

# ---------- Main / Daemon ----------
def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest GroupMe messages into SQLite (backfill + live head-sweep + reconcile).")
    parser.add_argument("--test", action="store_true",
                        help="Test backfill: stop after ~3 pages.")
    parser.add_argument("--no-topoff", action="store_true",
                        help="Skip head-sweep after backfilling.")
    parser.add_argument("--topoff-only", action="store_true",
                        help="Only run head-sweep (no backfill).")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-iteration progress.")
    parser.add_argument("--daemon", action="store_true",
                        help="Stay running and poll for new messages forever.")
    parser.add_argument("--interval", type=int, default=DAEMON_DEFAULT_INTERVAL,
                        help=f"Polling interval in seconds for --daemon (default: {DAEMON_DEFAULT_INTERVAL}).")
    parser.add_argument("--head-pages", type=int, default=3,
                        help="How many newest pages to scan each cycle to fill gaps (default: 3).")
    parser.add_argument("--reconcile-head", type=int, default=0,
                        help="Reconcile newest N pages (likes/reactions removals). 0=disabled.")
    args = parser.parse_args()

    started = datetime.now()
    total_reported = get_total_message_count()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    ensure_schema(conn)
    upsert_group_and_members(conn)

    # Topoff-only mode
    if args.topoff_only:
        added = topoff(conn, verbose=args.verbose, head_pages=args.head_pages)
        if args.reconcile_head > 0:
            _, ch = reconcile_head(conn, pages=args.reconcile_head, verbose=args.verbose)
        final = current_total(conn)
        print(f"✅ Top-off complete. Added {added} rows. Reconciled pages={args.reconcile_head} changes={ch if args.reconcile_head>0 else 0}. Total now {final:,}. DB: {DB_PATH}")
        return

    # One-time backfill (resume-safe)
    pages = backfill(conn, verbose=args.verbose, test_pages=(3 if args.test else None))
    added_after = 0 if args.no_topoff else topoff(conn, verbose=args.verbose, head_pages=args.head_pages)

    # Optional one-shot reconcile after initial sync
    recon_changes = 0
    if args.reconcile_head > 0:
        _, recon_changes = reconcile_head(conn, pages=args.reconcile_head, verbose=args.verbose)

    final_total = current_total(conn)
    elapsed = datetime.now() - started
    total_str = f"out of ~{total_reported:,}" if total_reported else ""
    print(f"✅ Sync complete. Messages in DB: {final_total:,} {total_str}. Backfill pages={pages}, topoff added={added_after}, reconcile changes={recon_changes}. Elapsed: {str(timedelta(seconds=int(elapsed.total_seconds())))}. DB: {DB_PATH}")

    # Daemon mode: keep polling for new messages forever
    if args.daemon:
        print(f"🟢 Daemon running… polling every {args.interval}s. Press Ctrl+C to stop.")
        try:
            while True:
                loop_start = time.time()
                added = topoff(conn, verbose=args.verbose, head_pages=args.head_pages)
                recon_changes = 0
                if args.reconcile_head > 0:
                    _, recon_changes = reconcile_head(conn, pages=args.reconcile_head, verbose=args.verbose)
                if args.verbose:
                    print(f"[daemon] cycle added={added} reconcile_changes={recon_changes} total={current_total(conn)} at {datetime.now().strftime('%H:%M:%S')}")
                # sleep remainder
                elapsed_loop = time.time() - loop_start
                to_sleep = max(1, args.interval - int(elapsed_loop))
                time.sleep(to_sleep)
        except KeyboardInterrupt:
            print("🛑 Daemon stopped by user.")
        finally:
            conn.close()

if __name__ == "__main__":
    main()
