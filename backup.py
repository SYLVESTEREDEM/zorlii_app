"""Scheduled backups of the SQLite database and media folders to an S3-compatible bucket.

Enabled only when ZORLII_BACKUP_BUCKET is set. Each cycle:
- writes a consistent SQLite snapshot with the sqlite3 backup API (safe while the app writes),
  and uploads it as db/<UTC timestamp>.sqlite3;
- uploads avatar and media files not yet in the bucket (their names are random and immutable);
- deletes database snapshots older than ZORLII_BACKUP_RETENTION_DAYS (default 14).
Media files are never deleted from the bucket by this module.
"""

import logging
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGGER = logging.getLogger("zorlii.backup")
MEDIA_FOLDERS = ("avatars", "media")


def config_from_env(environ=os.environ):
    bucket = environ.get("ZORLII_BACKUP_BUCKET", "").strip()
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "endpoint_url": environ.get("ZORLII_BACKUP_ENDPOINT") or None,
        "region_name": environ.get("ZORLII_BACKUP_REGION") or "auto",
        "aws_access_key_id": environ.get("ZORLII_BACKUP_ACCESS_KEY_ID") or None,
        "aws_secret_access_key": environ.get("ZORLII_BACKUP_SECRET_ACCESS_KEY") or None,
        "interval": int(environ.get("ZORLII_BACKUP_INTERVAL_SECONDS", "3600")),
        "retention_days": int(environ.get("ZORLII_BACKUP_RETENTION_DAYS", "14")),
    }


def snapshot_database(source_path, target_path):
    """Copy a live SQLite database to target_path using the online backup API."""
    source = sqlite3.connect(str(source_path), timeout=30)
    try:
        target = sqlite3.connect(str(target_path))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def list_keys(client, bucket, prefix):
    keys = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.add(item["Key"])
    return keys


def sync_media(client, bucket, data_dir):
    """Upload media files that the bucket does not have yet. Returns the number uploaded."""
    existing = list_keys(client, bucket, "media/")
    uploaded = 0
    for folder in MEDIA_FOLDERS:
        base = Path(data_dir) / folder
        if not base.is_dir():
            continue
        for path in base.iterdir():
            if not path.is_file():
                continue
            key = f"{folder}/{path.name}"
            if key in existing:
                continue
            client.upload_file(str(path), bucket, key)
            uploaded += 1
    return uploaded


def prune_snapshots(client, bucket, retention_days, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for key in list_keys(client, bucket, "db/"):
        stamp = key[len("db/"):].removesuffix(".sqlite3")
        try:
            taken = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if taken < cutoff:
            client.delete_object(Bucket=bucket, Key=key)
            removed += 1
    return removed


def run_backup(client, bucket, db_path, data_dir, retention_days, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "zorlii.sqlite3"
        snapshot_database(db_path, snapshot)
        client.upload_file(str(snapshot), bucket, f"db/{stamp}.sqlite3")
    media_count = sync_media(client, bucket, data_dir)
    pruned = prune_snapshots(client, bucket, retention_days, now)
    LOGGER.info("backup %s done: %d media uploaded, %d old snapshots removed", stamp, media_count, pruned)


def start_backup_thread(db_path, data_dir, environ=os.environ):
    """Start the daemon thread when backups are configured. Returns the thread or None."""
    config = config_from_env(environ)
    if config is None:
        return None
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        region_name=config["region_name"],
        aws_access_key_id=config["aws_access_key_id"],
        aws_secret_access_key=config["aws_secret_access_key"],
    )

    def loop():
        while True:
            try:
                run_backup(client, config["bucket"], db_path, data_dir, config["retention_days"])
            except Exception:
                LOGGER.exception("backup failed; will retry next interval")
            time.sleep(config["interval"])

    thread = threading.Thread(target=loop, name="zorlii-backup", daemon=True)
    thread.start()
    return thread
