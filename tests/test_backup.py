import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zorlii_app import backup


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_paginator(self, name):
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = [{"Key": k} for k in sorted(client.objects) if k.startswith(Prefix)]
                yield {"Contents": keys}

        return Paginator()

    def upload_file(self, filename, bucket, key):
        self.objects[key] = Path(filename).read_bytes()

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


class BackupTests(unittest.TestCase):
    def test_backup_uploads_snapshot_media_and_prunes_old_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            db_path = data / "zorlii.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
                connection.execute("INSERT INTO users(email) VALUES ('a@example.com')")
            (data / "media").mkdir()
            (data / "media" / "a.jpg").write_bytes(b"img")
            (data / "avatars").mkdir()
            (data / "avatars" / "b.jpg").write_bytes(b"avatar")

            client = FakeS3()
            old = datetime.now(timezone.utc) - timedelta(days=30)
            client.objects[f"db/{old.strftime('%Y%m%dT%H%M%SZ')}.sqlite3"] = b"old"
            now = datetime.now(timezone.utc)

            backup.run_backup(client, "bucket", db_path, data, retention_days=14, now=now)

            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            self.assertIn(f"db/{stamp}.sqlite3", client.objects)
            self.assertNotIn(f"db/{old.strftime('%Y%m%dT%H%M%SZ')}.sqlite3", client.objects)
            self.assertEqual(client.objects["media/a.jpg"], b"img")
            self.assertEqual(client.objects["avatars/b.jpg"], b"avatar")

            restored = Path(tmp) / "restored.sqlite3"
            restored.write_bytes(client.objects[f"db/{stamp}.sqlite3"])
            with sqlite3.connect(restored) as connection:
                self.assertEqual(connection.execute("SELECT email FROM users").fetchone()[0], "a@example.com")

    def test_disabled_without_bucket(self):
        self.assertIsNone(backup.config_from_env({}))


if __name__ == "__main__":
    unittest.main()
