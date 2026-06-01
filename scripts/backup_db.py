"""Consistent SQLite backup for methodology-analyzer.

Uses SQLite's online-backup API, which is safe to run against a live WAL
database (no need to stop the app). Writes a timestamped snapshot next to the
DB by default; if R2_* env vars are present AND boto3 is installed, it also
uploads the snapshot to a Cloudflare R2 bucket for true off-disk recovery.

Run nightly via a Render Cron Job:
    python scripts/backup_db.py

Restore: download the desired snapshot, stop the service, replace the file at
$DB_PATH with it, restart.

Off-disk upload (optional) — set these env vars and `pip install boto3`:
    R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"),
)
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(os.path.dirname(DB_PATH), "backups"))
RETAIN = int(os.environ.get("BACKUP_RETAIN", "7"))


def make_snapshot():
    if not os.path.exists(DB_PATH):
        print(f"[backup] no DB at {DB_PATH}; nothing to do")
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(BACKUP_DIR, f"app-{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)          # online backup — consistent point-in-time copy
    dst.close()
    src.close()
    print(f"[backup] wrote {dest}")
    return dest


def prune():
    if not os.path.isdir(BACKUP_DIR):
        return
    snaps = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("app-") and f.endswith(".db"))
    for old in snaps[:-RETAIN]:
        os.remove(os.path.join(BACKUP_DIR, old))
        print(f"[backup] pruned {old}")


def upload_r2(path):
    bucket = os.environ.get("R2_BUCKET")
    endpoint = os.environ.get("R2_ENDPOINT_URL")
    if not (bucket and endpoint):
        return  # off-disk upload not configured — local snapshot only
    try:
        import boto3
    except ImportError:
        print("[backup] R2_* set but boto3 not installed; skipping upload")
        return
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    key = f"backups/{os.path.basename(path)}"
    s3.upload_file(path, bucket, key)
    print(f"[backup] uploaded to r2://{bucket}/{key}")


def main():
    snap = make_snapshot()
    if snap:
        upload_r2(snap)
    prune()


if __name__ == "__main__":
    sys.exit(main())
