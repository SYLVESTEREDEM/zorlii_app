import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MobileConfigTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise Expo dynamic config")
    def test_dynamic_config_preserves_project_and_allows_explicit_override(self):
        script = """
        const assert = require('node:assert/strict');
        const config = require('./app.json').expo;
        const apply = require('./app.config');
        delete process.env.EXPO_PUBLIC_EAS_PROJECT_ID;
        delete process.env.ZORLII_GOOGLE_SERVICES_FILE;
        assert.equal(apply({config}).extra.eas.projectId, config.extra.eas.projectId);
        assert.equal(apply({config}).android.googleServicesFile, undefined);
        process.env.EXPO_PUBLIC_EAS_PROJECT_ID = '12345678-1234-1234-1234-123456789abc';
        process.env.ZORLII_GOOGLE_SERVICES_FILE = 'C:\\\\firebase\\\\google-services.json';
        assert.equal(apply({config}).extra.eas.projectId, process.env.EXPO_PUBLIC_EAS_PROJECT_ID);
        assert.equal(apply({config}).android.googleServicesFile, process.env.ZORLII_GOOGLE_SERVICES_FILE);
        """
        result = subprocess.run(["node", "-e", script], cwd=ROOT / "mobile",
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
