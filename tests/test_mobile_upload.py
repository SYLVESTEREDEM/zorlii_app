import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MobileUploadTests(unittest.TestCase):
    def test_all_native_media_uploads_use_shared_multipart_transport(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('import { uploadMultipart } from "./upload";', mobile)
        self.assertIn("await uploadMultipart(`${API_URL}${path}`, method, body, token);", mobile)
        self.assertIn('await uploadRequest("/api/profile/avatar", body, "PUT");', mobile)
        self.assertIn('await uploadRequest("/api/posts/media", body);', mobile)
        self.assertIn('await uploadRequest(`/api/posts/${post.id}/replies/media`, body);', mobile)

    def test_composer_media_picker_drops_press_event_and_keeps_reply_routing(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("onPress={() => onPress()}", mobile)
        self.assertIn(
            'MediaPickerButton label="Attach photos, videos, or GIFs to post" onPress={() => pickPostMedia()}',
            mobile,
        )
        self.assertIn(
            'MediaPickerButton label="Attach photos, videos, or GIFs to reply" onPress={() => pickPostMedia(post.id)}',
            mobile,
        )

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_native_multipart_uses_xhr_and_surfaces_failures(self):
        source = (ROOT / "mobile" / "upload.ts").read_text(encoding="utf-8")
        script = """
        const assert = require('node:assert/strict');
        const ts = require(%s);
        const source = ts.transpile(%s, {module: ts.ModuleKind.CommonJS});
        let lastRequest;
        global.XMLHttpRequest = class {
          constructor() { lastRequest = this; this.headers = {}; }
          open(method, url) { this.method = method; this.url = url; }
          setRequestHeader(key, value) { this.headers[key] = value; }
          send(body) { this.body = body; }
        };
        const exports = {};
        new Function('exports', source)(exports);
        (async () => {
          const form = {};
          const pending = exports.uploadMultipart('https://example.test/avatar', 'PUT', form, 'token');
          assert.equal(lastRequest.method, 'PUT');
          assert.equal(lastRequest.url, 'https://example.test/avatar');
          assert.equal(lastRequest.headers.Authorization, 'Bearer token');
          assert.equal(lastRequest.headers['Content-Type'], undefined);
          assert.equal(lastRequest.body, form);
          lastRequest.status = 200;
          lastRequest.onload();
          await pending;

          const failed = exports.uploadMultipart('https://example.test/media', 'POST', form, '');
          assert.equal(lastRequest.headers.Authorization, undefined);
          lastRequest.status = 413;
          lastRequest.responseText = '{"detail":"Image is too large."}';
          lastRequest.onload();
          await assert.rejects(failed, /Image is too large/);

          const invalid = exports.uploadMultipart('https://example.test/media', 'POST', form, '');
          lastRequest.status = 500;
          lastRequest.responseText = 'invalid';
          lastRequest.onload();
          await assert.rejects(invalid, /Could not upload/);

          const offline = exports.uploadMultipart('https://example.test/media', 'POST', form, '');
          lastRequest.onerror();
          await assert.rejects(offline, /connection/);
        })().catch(error => { console.error(error); process.exitCode = 1; });
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(source))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
