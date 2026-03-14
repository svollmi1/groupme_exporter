# verify_coverage.py  — loud, defensive verifier

import os, sys, sqlite3, requests, traceback

TOKEN    = os.environ.get("GROUPME_TOKEN")
GROUP_ID = os.environ.get("GROUPME_GROUP_ID")

if not TOKEN or not GROUP_ID:
    print("ERROR: Missing required environment variables GROUPME_TOKEN and GROUPME_GROUP_ID")
    sys.exit(1)
BASE     = "https://api.groupme.com/v3"
HERE     = os.path.dirname(__file__)
DB       = os.path.join(HERE, "groupme.sqlite")

HDRS = {
    "Cache-Control": "no-cache",
    "If-None-Match": "",
    "If-Modified-Since": "Thu, 01 Jan 1970 00:00:00 GMT",
    "User-Agent": "groupme-verify/1.1",
}

def log(msg):
    print(msg, flush=True)

def api(path, **params):
    params["token"] = TOKEN
    for attempt in range(1, 7):
        try:
            r = requests.get(BASE + path, params=params, headers=HDRS, timeout=(10, 60))
            ct = (r.headers.get("Content-Type") or "")
            if r.status_code in (420, 429) or r.status_code >= 500:
                log(f"[api] retry {attempt} status={r.status_code} ct={ct!r}")
                continue
            if not r.content or "application/json" not in ct.lower():
                log(f"[api] retry {attempt} non-json/empty ct={ct!r} len={len(r.content) if r.content else 0}")
                continue
            return r.json().get("response", {})
        except Exception as e:
            log(f"[api] retry {attempt} exception: {type(e).__name__}: {e}")
            continue
    log("[api] giving up; returning empty {}")
    return {}

def main():
    log(f"=== verify_coverage.py starting ===")
    log(f"Python: {sys.version.split()[0]}  DB path: {DB}")
    if not os.path.exists(DB):
        log("ERROR: DB file not found.")
        sys.exit(2)

    # Open DB
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # List tables to confirm schema
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    log(f"Tables: {tables}")

    if "messages" not in tables:
        log("ERROR: 'messages' table not found. Did you run the ingestor in this folder?")
        sys.exit(3)

    # DB boundaries
    db_count = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    row_min  = con.execute("SELECT id FROM messages ORDER BY CAST(id AS INTEGER) ASC  LIMIT 1").fetchone()
    row_max  = con.execute("SELECT id FROM messages ORDER BY CAST(id AS INTEGER) DESC LIMIT 1").fetchone()
    db_min = row_min[0] if row_min else None
    db_max = row_max[0] if row_max else None
    log(f"DB count={db_count:,}  min_id={db_min}  max_id={db_max}")

    # Older-than-min
    if db_min:
        older = api(f"/groups/{GROUP_ID}/messages", limit=100, before_id=db_min)
        older_ct = len(older.get("messages", []) or [])
        log(f"API older-than-min: {older_ct} messages")
    else:
        log("No min_id (empty messages table).")

    # Newer-than-max
    if db_max:
        newer = api(f"/groups/{GROUP_ID}/messages", limit=100, since_id=db_max)
        newer_ct = len(newer.get("messages", []) or [])
        log(f"API newer-than-max: {newer_ct} messages")
    else:
        log("No max_id (empty messages table).")

    # Latest 200 spot check
    latest = api(f"/groups/{GROUP_ID}/messages", limit=200)
    latest_msgs = latest.get("messages", []) or []
    api_ids = [m.get("id") for m in latest_msgs if m.get("id")]
    missing = []
    for mid in api_ids:
        if not con.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone():
            missing.append(mid)
    log(f"Among latest {len(api_ids)} API messages, missing in DB: {len(missing)}")
    if missing[:10]:
        log("Sample missing ids: " + ", ".join(missing[:10]))

    log("=== verify_coverage.py done ===")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
