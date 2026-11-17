import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from zorlii_app.db import Database
from zorlii_app.main import new_app


ROOT = Path(__file__).resolve().parents[1]


class WebUiRegressionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to parse inline JavaScript")
    def test_inline_scripts_parse(self):
        class ScriptParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.scripts = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                if tag == "script" and "src" not in dict(attrs):
                    self.current = []

            def handle_data(self, data):
                if self.current is not None:
                    self.current.append(data)

            def handle_endtag(self, tag):
                if tag == "script" and self.current is not None:
                    self.scripts.append("".join(self.current))
                    self.current = None

        parser = ScriptParser()
        parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(parser.scripts)
        script = """
        const scripts=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        scripts.forEach((source,index)=>{
          try { new Function(source); }
          catch(error) { throw new SyntaxError(`Inline script ${index+1}: ${error.message}`); }
        });
        """
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps(parser.scripts),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_registration_uses_email_password_and_required_consent(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        registration = html.split("function authScreen", 1)[1].split("function", 1)[0]
        self.assertIn('const registrationFields=\'\'', registration)
        self.assertIn('name="email"', registration)
        self.assertIn('name="password"', registration)
        self.assertIn('name="accept_terms"', registration)
        self.assertIn(
            ".form input:not([type=checkbox]):not([type=hidden]){width:100%",
            html,
        )

    def test_logo_is_local_and_served_by_the_app_without_external_fonts(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/zorlii-logo.png"', html)
        self.assertTrue((ROOT / "assets" / "zorlii-logo.png").is_file())
        self.assertNotRegex(html, r"https?://")

        response = TestClient(new_app(Database(":memory:"))).get("/assets/zorlii-logo.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_login_branding_and_theme_button_contrast_are_consistent_on_web_and_mobile(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        theme_sync = html.split("function syncThemeStyles()", 1)[1].split("function updateMe", 1)[0]
        web_login = html.split("function authScreen", 1)[1].split("function", 1)[0]
        mobile_login = mobile.split('if (screen === "login")', 1)[1].split(
            'if (screen === "forgot")', 1
        )[0]

        self.assertIn(
            ') .primary{color:var(--accent-ink)!important}',
            theme_sync,
        )
        self.assertIn('class="auth-logo" aria-hidden="true"><img src="assets/zorlii-logo.png"', web_login)
        self.assertIn('#auth.form[data-mode="login"]:before,#auth.form[data-mode="login"]:after{content:none}', html)
        self.assertNotIn("Welcome back", web_login)
        self.assertIn("action('Continue to email verification'", web_login)
        self.assertIn("action('Sign in'", web_login)
        self.assertIn('authJourney("Sign in"', mobile_login)
        self.assertIn('source={require("./assets/zorlii-logo.png")}', mobile)
        self.assertIn("authBrandLogo: {", mobile)
        self.assertNotIn("Welcome back", mobile_login)
        self.assertIn('accessibilityLabel={label}', mobile)
        self.assertIn("secondary ? { color: safeAccent } : { color: themeText }", mobile)
        self.assertIn("includeFontPadding: false", mobile)

    def test_native_login_matches_mobile_layout_and_preserves_auth_actions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        login = mobile.split('if (screen === "login")', 1)[1].split(
            'if (screen === "forgot")', 1
        )[0]

        self.assertIn('authJourney("Sign in"', login)
        for copy in (
            "A thoughtful little corner",
            "Make room for the conversations that matter.",
            "Discover people and conversations, send private messages, and play mini games.",
        ):
            self.assertIn(copy, mobile)
        self.assertIn('field("email", "Email address", false, false, "Email")', login)
        self.assertIn('field("password", "Password", true, false, "Password")', login)
        self.assertIn('authAction("Sign in", () => { void submitAuth(); }, true, "Signing in…")', login)
        self.assertIn('authAction("Create an account", () => setScreen("register"))', login)
        self.assertIn('authAction("Forgot password?", () => setScreen("forgot"))', login)
        self.assertIn("visibleLabel || placeholder", mobile)
        self.assertIn('screen !== "messages" && !authScreenActive ? <View style={[styles.header', mobile)
        self.assertIn('me?.terms_accepted && screen !== "messages" && !authScreenActive ?', mobile)
        self.assertIn("paddingTop: compactAuth ? Math.max(12, insets.top) : Math.max(20, insets.top + 10)", mobile)
        self.assertIn('automaticallyAdjustKeyboardInsets={Platform.OS === "ios"}', mobile)
        self.assertIn('backgroundColor: "transparent"', mobile.split("authAction:", 1)[1].split("\n", 1)[0])
        self.assertIn('minHeight: 44', mobile.split("authAction:", 1)[1].split("\n", 1)[0])
        self.assertIn('.auth-identity .auth-logo{width:62px;height:62px;margin-bottom:10px}', html)
        self.assertIn('.auth-identity h1{font-size:30px}', html)
        self.assertIn('.auth-shell .auth-form,#auth.form.auth-form{padding:16px}', html)
        self.assertIn('width: 62, height: 62, borderRadius: 31', mobile)
        self.assertIn('fontFamily: "serif", fontSize: 30', mobile)
        self.assertIn('backgroundColor: mixColor(themeColor, "#0b0d1d", 0.14)', mobile)
        self.assertIn('borderColor: mixColor(safeAccent, "#282744", 0.32)', mobile)
        self.assertIn('authBrandLogoCompact', mobile)
        self.assertIn('!compactAuth ? <Text style={styles.authIntroDescription}', mobile)

        password_toggle = mobile.split("authPasswordToggle: {", 1)[1].split("}", 1)[0]
        self.assertIn("minHeight: 44", password_toggle)
        self.assertIn("minWidth: 44", password_toggle)
        self.assertIn('backgroundColor: "transparent"', password_toggle)
        self.assertNotIn("borderWidth", password_toggle)
        self.assertNotIn("borderColor", password_toggle)

    def test_native_auth_gradients_match_web_without_changing_other_screen_themes(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn('type: "radial-gradient"', mobile)
        self.assertIn('position: { top: "0%", left: "50%" }', mobile)
        self.assertIn('direction: "160deg"', mobile)
        self.assertIn('direction: "150deg"', mobile)
        self.assertIn("backgroundImage: AUTH_PAGE_BACKGROUND_IMAGE", mobile)
        self.assertIn("backgroundImage: AUTH_CARD_BACKGROUND_IMAGE", mobile)
        self.assertIn(
            "authScreenActive ? styles.authScreenBackground : { backgroundColor: palette.background }",
            mobile,
        )
        self.assertIn(
            "authScreenActive ? styles.authScroll : { backgroundColor: palette.background }",
            mobile,
        )

    def test_auth_journeys_use_accessible_text_actions_without_changing_routes(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_auth = html.split("function authScreen", 1)[1].split("function renderTermsAcceptance", 1)[0]

        for form_id in ("auth", "verify-register", "forgot", "verify-reset"):
            self.assertIn(f'class="form auth-form" id="{form_id}"', web_auth)
        for action in (
            'data-auth="register"',
            'data-auth="forgot"',
            'data-auth="login"',
            'data-action="resend-signup"',
            'data-action="resend-recovery"',
            'href="/terms"',
            'href="/privacy"',
        ):
            self.assertIn(action, web_auth)
        self.assertIn("auth-action-primary", web_auth)
        self.assertNotIn('class="primary"', web_auth)
        self.assertIn('type="${primary?\'submit\':\'button\'}"', web_auth)
        self.assertIn("data-auth=\"${reg?'login':'register'}\"", web_auth)
        self.assertNotIn('data-auth="${reg?\'login\':\'register\'}<span', web_auth)
        self.assertIn('class="auth-action" href="/terms"', web_auth)
        self.assertIn("min-height:44px", html)
        self.assertIn("text-decoration:none!important", html)
        self.assertIn(".auth-action:focus-visible", html)
        self.assertIn("authForm=f.matches('#auth,#verify-register,#forgot,#verify-reset')", html)
        self.assertIn("if(!b||b.disabled)return", html)
        self.assertIn("function ensurePasswordPolicyStatus(input)", html)
        self.assertIn('#verify-reset .password-field input[name="password"]', html)
        self.assertIn("width:0!important;max-width:100%", html)

        for route in ("register", "verify-register", "forgot", "reset-code"):
            self.assertIn(f'if (screen === "{route}") return authJourney(', mobile)
        self.assertIn("const authAction = (label: string, action: () => void", mobile)
        for action in (
            'authAction("Continue to email verification"',
            'authAction("Verify and create account"',
            'authAction("Send verification code"',
            'authAction("Verify code and update password"',
            'authAction("Resend code"',
            'authAction("Change email"',
        ):
            self.assertIn(action, mobile)
        self.assertIn("authSubmissionRef.current", mobile)
        self.assertIn('passwordFieldRow: { width: "100%"', mobile)
        self.assertIn("passwordInput: { flex: 1, minWidth: 0, width: 0 }", mobile)
        self.assertIn('"/api/auth/register"', mobile)
        self.assertIn('"/api/auth/register/verify"', mobile)
        self.assertIn('"/api/auth/forgot-password"', mobile)
        self.assertIn('"/api/auth/reset-password"', mobile)
        self.assertIn('authAction("Terms of Use"', mobile)
        self.assertIn('authAction("Privacy Policy"', mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise auth-screen markup")
    def test_create_account_action_renders_a_valid_registration_route(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        auth_source = "function authScreen" + html.split("function authScreen", 1)[1].split(
            "function renderTermsAcceptance", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        let page;
        const renderAuth=new Function('esc','base','pendingSignupEmail','pendingRecoveryEmail',
          'passwordPolicyPattern','passwordPolicyMessage',source+';return authScreen;')(
            value=>String(value??''),(content,aside,pageClass)=>{page={content,pageClass};},
            'qa@example.test','qa@example.test','password-pattern','password-policy');
        renderAuth('login');
        assert.match(page.content,/<button type="button" class="auth-action" data-auth="register"><span class="auth-action-label">Create an account<\\/span><\\/button>/);
        assert.equal(page.pageClass,'auth-shell-page');
        renderAuth('register');
        assert.match(page.content,/<form class="form auth-form" id="auth" data-mode="register">/);
        assert.match(page.content,/<input type="email" name="email"/);
        assert.match(page.content,/<input type="checkbox" name="accept_terms"/);
        renderAuth('verify-register');
        assert.match(page.content,/<form class="form auth-form" id="verify-register">/);
        assert.match(page.content,/name="code"/);
        """
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps(auth_source),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_mobile_primary_label_foreground_contrasts_with_supported_theme_accents(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        helpers = "function colorLuminance" + mobile.split("function colorLuminance", 1)[1].split(
            "\ntype HslColor", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'),ts=require(%s);
        const helpers=ts.transpile(%s),colors=['#a47dff','#ffffff','#000000','#ff0000','#00ff00','#ffff00'];
        const contrast=(a,b)=>{
          const lum=color=>color.slice(1).match(/.{2}/g).map(part=>parseInt(part,16)/255)
            .map(channel=>channel<=0.04045?channel/12.92:((channel+0.055)/1.055)**2.4)
            .reduce((sum,channel,index)=>sum+channel*[0.2126,0.7152,0.0722][index],0);
          const values=[lum(a),lum(b)].sort((x,y)=>y-x); return (values[0]+0.05)/(values[1]+0.05);
        };
        const results=new Function('contrast','colors',helpers+';return colors.map(theme=>{const background=readableAccent(theme),foreground=contrastForeground(background);return {theme,background,foreground,ratio:contrast(background,foreground)}})')(contrast,colors);
        for(const result of results) assert.ok(result.ratio>=4.5,JSON.stringify(result));
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(helpers))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_registration_and_recovery_use_otp_not_reset_links(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="verify-register"', html)
        self.assertIn('id="verify-reset"', html)
        self.assertIn('data-action="resend-signup"', html)
        self.assertIn('data-action="resend-recovery"', html)
        self.assertIn("/api/auth/register/verify", html)
        self.assertIn("/api/auth/reset-password", html)
        self.assertIn('name="code"', html)
        self.assertNotIn("URLSearchParams(location.search).get('token')", html)
        self.assertNotIn("reset link", html.lower())

    def test_password_policy_and_social_activity_ui_are_exposed(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("4–128 characters", html)
        self.assertIn("passwordPolicyPattern", html)
        self.assertIn('data-go="notifications">Activities', html)
        self.assertIn("<h1>Activities</h1>", html)
        self.assertIn("/api/notifications/read", html)
        self.assertIn("/followers?limit=1", html)
        self.assertIn("/following?limit=1", html)
        self.assertIn("renderSocialList(kind,username=me.username)", html)
        self.assertIn('data-go="social-followers"', html)
        self.assertIn('data-go="social-following"', html)
        self.assertIn("4–128 characters", mobile)
        self.assertIn('"/api/notifications"', mobile)
        self.assertIn('"/api/notifications/read"', mobile)
        self.assertIn("/followers", mobile)
        self.assertIn("/following", mobile)

    def test_quiz_games_render_server_choices_and_require_rules_acknowledgement(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        games = (ROOT / "mobile" / "Games.tsx").read_text(encoding="utf-8")
        for game_id in ("quick-math", "word-scramble", "odd-one-out", "number-pattern", "color-match"):
            self.assertIn(f'"{game_id}"', html)
            self.assertIn(f'"{game_id}"', games)
        self.assertIn("state.choices.map(choice", html)
        self.assertIn("data-move=\"${esc(choice.id)}\"", html)
        self.assertIn("state.correct", html)
        self.assertIn("gameRulesAccepted", html)
        self.assertIn('id="game-rules-ack"', html)
        self.assertIn("run.state.choices.map(choice", games)
        self.assertIn('accessibilityRole="checkbox"', games)
        self.assertIn("rulesAccepted[game.id]", games)

    def test_empty_inbox_has_non_destructive_creator_welcome(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("const welcome = !rows ?", html)
        self.assertIn("💜 Welcome to the Zorlii community. Let's make every connection count! — Creator", html)
        self.assertIn("!conversations.length && <View", mobile)
        self.assertIn("💜 Welcome to the Zorlii community. Let's make every connection count! — Creator", mobile)

    def test_mobile_push_registration_and_notification_handling(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        app_json = (ROOT / "mobile" / "app.json").read_text(encoding="utf-8")
        app_config = (ROOT / "mobile" / "app.config.js").read_text(encoding="utf-8")
        self.assertIn("if (!canRegisterPushToken(Platform.OS, Device.isDevice)) return false;", mobile)
        self.assertIn("getExpoPushTokenAsync({ projectId })", mobile)
        self.assertIn('"/api/push-token"', mobile)
        self.assertIn("addNotificationResponseReceivedListener", mobile)
        self.assertIn('"expo-notifications"', app_json)
        self.assertIn("EXPO_PUBLIC_EAS_PROJECT_ID", app_config)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise the local push platform guard")
    def test_android_emulator_can_attempt_push_registration_without_network_calls(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        match = re.search(
            r"function canRegisterPushToken\(platform: string, isDevice: boolean\) \{\s*return ([^;]+);",
            mobile,
        )
        self.assertIsNotNone(match)
        script = """
        const assert = require('node:assert/strict');
        const canRegisterPushToken = (platform, isDevice) => %s;
        assert.equal(canRegisterPushToken('android', false), true);
        assert.equal(canRegisterPushToken('android', true), true);
        assert.equal(canRegisterPushToken('ios', true), true);
        assert.equal(canRegisterPushToken('ios', false), false);
        assert.equal(canRegisterPushToken('web', true), false);
        """ % match.group(1)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_account_data_controls_are_available_in_web_and_mobile(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('data-action="export-account"', html)
        self.assertIn('data-go="delete-account"', html)
        self.assertIn("/api/account/export", html)
        self.assertIn('id="delete-account"', html)
        self.assertIn("without @", html)
        self.assertIn('"/api/account/export"', mobile)
        self.assertIn('"/api/account"', mobile)
        self.assertIn("Share.share", mobile)
        self.assertIn("Delete account", mobile)

    def test_profile_photo_controls_and_privacy_copy_exist_on_both_clients(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('id="avatar-file"', html)
        self.assertIn("PUT", html)
        self.assertIn("DELETE", html)
        self.assertIn("avatarMarkup", html)
        self.assertIn("No generative AI service is used", html)
        self.assertIn("local extractive context help", html)
        self.assertIn("expo-image-picker", mobile)
        self.assertIn("pickAvatar", mobile)
        self.assertIn("Remove profile photo", mobile)
        self.assertIn("avatar_url", mobile)
        self.assertIn("No generative AI service.", mobile)

    def test_empty_states_and_opt_in_local_assistance_remain_explicit(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("New conversations will appear here when members share them.", html)
        self.assertIn("Your inbox is quiet.", html)
        self.assertIn("recommendations_consent", html)
        self.assertIn("context_assistance_consent", html)
        self.assertIn("no generated answers are produced.", html.lower())
        self.assertIn("Conversations shared by real Zorlii members will appear here.", mobile)
        self.assertIn("Suggestions use real public member posts; none may be available yet.", mobile)
        self.assertIn("Confirm use of this text for this request first.", mobile)
        self.assertIn('accessibilityRole="checkbox" accessibilityState={{ checked: form.context_confirm === "true" }}', mobile)

    def test_mobile_navigation_and_empty_state_have_compact_brand_signature(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(5,minmax(0,1fr))", html)
        self.assertIn('button.setAttribute("aria-label", `Activities${unreadLabel}`)', html)
        self.assertIn(".empty:before,#auth.form:before{border:1px solid #62596a!important", html)
        self.assertIn(".empty:after,#auth.form:after{background:#83a89b!important", html)
        self.assertIn("animation:none!important", html)
        self.assertIn("function BrandHalo(", mobile)
        self.assertIn("<BrandHalo size={42} showLogo />", mobile)
        self.assertIn("<BrandHalo size={58} quiet />", mobile)
        self.assertIn('data-go="settings"', html)
        self.assertIn("async function renderSettings()", html)
        self.assertIn("Community safety", html)
        self.assertIn('disclosure("account-help", "Notifications, help & account"', mobile)
        self.assertIn('data-go="blocks"', html)
        self.assertIn('setScreen("blocked")', mobile)
        self.assertIn("styles.avatarHalo", mobile)
        self.assertIn("styles.avatarPulse", mobile)

    def test_create_navigation_targets_the_existing_composer_on_both_clients(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('data-action="create-post"', html)
        self.assertIn("document.getElementById('post-body')?.focus()", html)
        self.assertIn('["feed", "explore", "create", "inbox", "profile"]', mobile)
        self.assertIn("composerRef.current?.focus()", mobile)
        composer = mobile.split('<TextInput ref={composerRef}', 1)[1].split("/>", 1)[0]
        self.assertIn("placeholderTextColor={palette.muted}", composer)
        self.assertIn("Privacy &amp; local tools", html)
        self.assertIn("Privacy & local tools", mobile)

    def test_mobile_navigation_keeps_secondary_destinations_in_right_side_menu(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn('aria-controls="app-drawer" aria-expanded="false"', html)
        self.assertIn('role="dialog" aria-modal="true"', html)
        self.assertIn("setDrawerOpen(false)", html)
        self.assertIn("event.key==='Escape'", html)
        self.assertIn('right:max(12px,env(safe-area-inset-right));left:auto', html)
        self.assertNotIn('.menu-toggle{top:12px;left:12px', html)
        self.assertIn("inset:0 0 0 auto", html)
        self.assertGreater(html.rindex(".menu-drawer{inset:0 0 0 auto"), html.index(".menu-drawer{position:fixed;inset:0 auto 0 0"))
        self.assertIn(".menu-drawer.open{transform:translateX(0)}", html)
        self.assertIn('data-go="notifications">Activities${activityUnreadCount?', html)
        self.assertIn('data-go="games">Mini games</button>', html)
        self.assertIn('data-go="notifications"],.nav button[data-go="moderation"]{display:none!important}', html)
        self.assertIn('accessibilityLabel={unreadNotifications ? `Open menu, ${unreadNotifications} unread activities` : "Open menu"}', mobile)
        self.assertIn('accessibilityState={{ expanded: menuOpen }}', mobile)
        self.assertIn('menuButton("Activities", () => { setScreen("notifications"); void loadNotifications(); }, unreadNotifications)', mobile)
        self.assertIn("styles.menuUnreadBadge", mobile)
        self.assertIn('accessibilityLabel={unreadNotifications ? `Open menu, ${unreadNotifications} unread activities` : "Open menu"}', mobile)
        self.assertIn('menuButton("Mini games"', mobile)
        self.assertIn('menuModalRoot: { flex: 1, flexDirection: "row-reverse"', mobile)
        self.assertIn('width: menuDrawerWidth', mobile)
        self.assertIn('menuDrawer: { maxWidth: 360', mobile)

    def test_mobile_first_use_copy_and_primary_actions_keep_neon_brand_accent(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("Discover people and conversations, send private messages, and play mini games.", html)
        self.assertIn(".auth-features{max-width:48ch", html)
        self.assertIn(".primary{background:#8b35ff;color:#fff", html)
        self.assertIn(".nav button[data-action=\"create-post\"] .nav-symbol{background:#8b35ff", html)
        self.assertIn("#auth.form{padding:14px;padding-top:90px;margin-top:12px}", html)
        self.assertIn(".auth-features{margin-bottom:12px}", html)

    def test_echo_sharing_is_a_combined_accessible_action_on_web_and_mobile(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_cards = html.split("function echoMenuMarkup", 1)[1].split("async function renderReport", 1)[0]
        mobile_cards = mobile.split("const replyCard =", 1)[1].split("return <KeyboardAvoidingView", 1)[0]
        dark_styles = html[html.rfind(":root{color-scheme:dark;--ink:#f4f1ff"):].split("</style>", 1)[0]
        mobile_styles = dark_styles[dark_styles.rfind("@media(max-width:670px)"):]

        self.assertIn("Echo with a thought", web_cards)
        self.assertIn('data-action="echo-thought"', web_cards)
        self.assertIn("aria-haspopup", web_cards)
        self.assertIn("socialActionIcon('repost',item.reposted)", web_cards)
        self.assertNotIn('data-action="repost"', web_cards)
        self.assertNotIn('data-action="quote"', web_cards)
        self.assertIn('window.socialActionIcon("reply")', html)
        self.assertIn('window.socialActionIcon("bookmark", saved)', html)
        self.assertIn('name="repost"', mobile)
        self.assertIn('socialAction("Open thread", "reply"', mobile)
        self.assertIn('socialAction(post.bookmarked ? "Remove saved post" : "Save post", "bookmark"', mobile)
        self.assertIn('post.reacted ? "#ff4f73" : undefined', mobile)
        self.assertIn("socialAction: { minWidth: 44, minHeight: 44", mobile)
        self.assertNotIn("borderWidth: 1", mobile.split("socialAction: {", 1)[1].split("}", 1)[0])
        self.assertIn(".quiet.pulse-refresh:focus-visible", html)
        self.assertIn('aria-label="Refresh Pulse"', html)
        self.assertIn("border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important", html)
        self.assertIn("visible={!!echoTarget}", mobile)
        self.assertIn('onRequestClose={() => setEchoTarget(null)}', mobile)
        self.assertIn('accessibilityLabel="Close Echo options"', mobile)
        self.assertIn('onPress={() => chooseEcho("echo")}', mobile)
        self.assertIn('onPress={() => chooseEcho("thought")}', mobile)
        self.assertNotIn('Alert.alert("Echo"', mobile)
        self.assertIn("accessibilityHint=", mobile)
        self.assertNotIn('button("Repost', mobile_cards)
        self.assertNotIn('button("Quote"', mobile_cards)
        self.assertIn("Add a thought before Echoing the original.", html)
        self.assertIn("Add a thought before Echoing the original.", mobile)
        self.assertEqual(dark_styles.count("@media(max-width:670px)"), 1)
        self.assertIn("linear-gradient(160deg,#070713,#0b1020 68%,#090b18)", mobile_styles)
        self.assertIn(".sidebar{background:#0b1020f2", mobile_styles)
        self.assertIn(".nav button.active{background:transparent;box-shadow:inset 0 -2px #a47dff}", mobile_styles)
        self.assertIn(".nav button[data-action=\"create-post\"] .nav-symbol{background:linear-gradient", mobile_styles)
        self.assertNotIn("background:linear-gradient(160deg,#11131f", mobile_styles)
        self.assertNotIn(".nav button.active{background:#302c39", mobile_styles)

    def test_pulse_uses_a_light_signal_timeline_and_inline_refresh(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('class="pulse-title-row"', html)
        self.assertIn('class="pulse-wave" aria-hidden="true"', html)
        self.assertIn('class="quiet pulse-refresh"', html)
        self.assertIn(".main #feed-posts>.post{position:relative;padding:18px 10px 20px;margin:6px 0;background:transparent!important", html)
        self.assertIn(".nav button.active{background:transparent!important;color:var(--accent-readable)!important", html)
        self.assertIn("styles.pulseTimeline", mobile)
        self.assertIn("pulsePost: { borderWidth: 0, borderBottomWidth: 1", mobile)
        self.assertIn("styles.pulseNode", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise vector icons")
    def test_web_social_icons_are_accessible_inline_vectors(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        icon_function = "function socialActionIcon" + html.split(
            "function socialActionIcon", 1
        )[1].split("function profileLinkMarkup", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        const icon=new Function(`${source};return socialActionIcon`)();
        for(const name of ['heart','repost','reply','bookmark']){
          const markup=icon(name);
          assert.match(markup,/<svg class="social-icon"/);
          assert.match(markup,/aria-hidden="true"/);
          assert.match(markup,/viewBox="0 0 24 24"/);
        }
        assert.match(icon('bookmark'),/fill="none"/);
        assert.match(icon('bookmark',true),/fill="currentColor"/);
        assert.match(icon('heart',true),/fill="currentColor"/);
        """
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(icon_function),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_media_uploads_and_white_card_text_are_available_without_limit_copy(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('accept="image/*,video/*" multiple', html)
        self.assertIn("api('/api/posts/media'", html)
        self.assertIn('<video controls preload="metadata"', html)
        self.assertIn('mediaTypes: ["images", "videos"]', mobile)
        self.assertIn('"/api/posts/media"', mobile)
        self.assertIn("VideoView", mobile)
        self.assertIn(".notification-item p{margin:5px 0 10px;color:var(--ink)}", html)
        self.assertIn("background:#fff!important;color:#000!important", html)
        self.assertIn("-webkit-text-fill-color:#000!important;caret-color:#000", html)
        self.assertNotIn("Profile photos must be 2 MB", html)
        self.assertNotIn("2 MB", mobile)

    def test_media_attach_controls_are_icon_only_and_accessible_on_both_clients(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertNotIn("Add pictures or videos", html)
        self.assertNotIn("Add photos or videos", mobile)
        self.assertIn('aria-label="Attach photos, videos, or GIFs to post"', html)
        self.assertIn('aria-label="Attach photos, videos, or GIFs to reply"', html)
        self.assertIn('min-width:44px;min-height:44px', html)
        self.assertIn('<span aria-hidden="true">+</span>', html)
        self.assertIn('label="Attach photos, videos, or GIFs to post"', mobile)
        self.assertIn('label="Attach photos, videos, or GIFs to reply"', mobile)
        self.assertIn("mediaPickerButton:", mobile)
        self.assertIn("style={[styles.mediaPickerIcon, { color: readableAccent(activeThemeAccent) }]} accessibilityElementsHidden", mobile)
        self.assertIn("accessibilityElementsHidden>+</Text>", mobile)

    def test_compact_composers_keep_media_previews_and_accessible_arrow_actions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_reply = html.split("function replyComposerMarkup", 1)[1].split("function nav()", 1)[0]
        web_feed = html.split("async function renderFeed()", 1)[1].split("function replyMarkup", 1)[0]
        mobile_reply = mobile.split("const postCard =", 1)[1].split("function renderBody()", 1)[0]
        mobile_feed = mobile.split('return <View>\n      <Text style={[styles.eyebrow, { color: safeAccent }]}>Your community', 1)[1].split(
            "\n  }\n\n  return <KeyboardAvoidingView", 1
        )[0]

        self.assertIn('<input type="text" id="reply-body-${postId}" name="body"', web_reply)
        self.assertIn('aria-label="Send reply"', web_reply)
        self.assertIn('id="reply-selected-${postId}"', web_reply)
        self.assertIn('aria-label="Share post"', web_feed)
        self.assertIn('id="post-media"', web_feed)
        self.assertNotIn("Share thought", web_feed)
        self.assertIn("styles.replyInput", mobile_reply)
        self.assertIn("styles.arrowSubmit", mobile_reply)
        self.assertIn("MediaPickerButton label=\"Attach photos, videos, or GIFs to reply\"", mobile_reply)
        self.assertIn("styles.arrowSubmit", mobile_feed)
        self.assertIn("MediaPickerButton label=\"Attach photos, videos, or GIFs to post\"", mobile_feed)
        self.assertIn("setReplyMediaByPost(current => ({ ...current, [post.id]: (current[post.id] || []).filter", mobile)
        self.assertIn("setPostMedia(current => current.filter", mobile)
        self.assertIn('asset.mimeType?.toLowerCase() || "application/octet-stream"', mobile)
        self.assertIn("function nativeUploadName(fileName:", mobile)
        self.assertIn('"image/png": "png", "image/webp": "webp", "image/gif": "gif"', mobile)
        self.assertIn('mimeType === "application/octet-stream" ? "bin"', mobile)
        self.assertIn('nativeUploadName(asset.fileName, `media-${index}`, type)', mobile)
        self.assertIn("await uploadMultipart(`${API_URL}${path}`, method, body, token)", mobile)
        self.assertNotIn('asset.mimeType?.toLowerCase() || "image/jpeg"', mobile)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed to exercise upload filename handling")
    def test_mobile_upload_names_preserve_real_mime_and_unknown_binary_fallback(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        helper = "function nativeUploadName" + mobile.split("function nativeUploadName", 1)[1].split(
            "\nconst DEFAULT_ACCENT", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        const ts=require(%s);
        const nativeUploadName=new Function(ts.transpile(%s)+'; return nativeUploadName;')();
        for(const [type,extension] of [
          ['image/jpeg','jpg'],['image/png','png'],['image/webp','webp'],['image/gif','gif'],
          ['video/quicktime','mov']
        ]) assert.equal(nativeUploadName(null,'media',type),`media.${extension}`);
        assert.equal(nativeUploadName(null,'media','application/octet-stream'),'media.bin');
        assert.equal(nativeUploadName('photo.png','media','image/png'),'photo.png');
        """
        result = subprocess.run(
            ["node", "-e", script % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")),
                                      json.dumps(helper))],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_feed_polling_inserts_new_posts_automatically_and_preserves_reader_state(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_poll = html.split("refreshLive = async function", 1)[1].split("startLiveRefresh();", 1)[0]
        web_inplace = html.split("refreshFeedInPlace = async function", 1)[1].split("refreshLive = async function", 1)[0]
        mobile_poll = mobile.split("const refreshVisibleScreen = async () =>", 1)[1].split(
            "const stateSubscription", 1
        )[0]

        self.assertIn("refreshFeedInPlace()", web_poll)
        self.assertIn("updateFeedPosts(data.posts)", web_inplace)
        self.assertIn("await refreshFeedInPlace();else await renderFeed()", html)
        self.assertNotIn("pendingFeedPosts", html)
        self.assertNotIn("apply-new-posts", html)
        self.assertIn("replacement?.replaceWith(form)", html)
        self.assertIn("focusedElement.setSelectionRange(selection.start, selection.end, selection.direction)", html)
        self.assertIn("JSON.stringify(currentPosts) === JSON.stringify(newPosts)", html)
        self.assertNotIn("expandedReplyPosts.has(p.id)", web_inplace)
        self.assertIn("data-action=\"open-thread\"", html)
        self.assertIn("window.scrollBy(0, nextAnchor.getBoundingClientRect().top - anchorState.top)", html)
        self.assertIn("JSON.stringify(postsRef.current) === JSON.stringify(incoming)", mobile_poll)
        self.assertIn("feedInsertionAnchor(postsRef.current, incoming, feedPostPositionsRef.current)", mobile_poll)
        self.assertIn("postsRef.current = incoming", mobile_poll)
        self.assertIn("setPosts(incoming)", mobile_poll)
        self.assertNotIn("pendingPosts", mobile)
        self.assertIn("feedGeneration !== feedRequestRef.current", mobile_poll)
        self.assertIn("pollId !== feedPollRef.current", mobile_poll)
        self.assertIn('accessibilityLabel="Refresh Pulse"', mobile)

    def test_media_endpoints_and_thread_pagination_stay_separate(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_composer = html.split("else if(f.id==='compose'){", 1)[1].split("}else if(f.id==='search-form'){", 1)[0]
        web_reply = html.split("}else if(f.matches('[data-reply]')){", 1)[1].split("\n        }\n      }catch", 1)[0]
        native_post = mobile.split("async function sharePost()", 1)[1].split("\n\n  const field", 1)[0]
        native_reply = mobile.split("async function sendReply(post:", 1)[1].split("\n  function contentText", 1)[0]
        native_thread = mobile.split("async function refreshThread(", 1)[1].split("\n  function leaveThread", 1)[0]
        web_thread = html.split("async function refreshThread({initial=false}", 1)[1].split("async function loadMoreThreadReplies()", 1)[0]

        self.assertIn("api('/api/posts/media'", web_composer)
        self.assertIn("`/api/posts/${postId}/replies/media`", web_reply)
        self.assertIn('"/api/posts/media"', native_post)
        self.assertIn("`/api/posts/${post.id}/replies/media`", native_reply)
        self.assertIn("readThreadPages<Post, Reply>", native_thread)
        self.assertIn("after_id=${encodeURIComponent(cursor)}&limit=100", native_thread)
        self.assertIn("while(hasMore&&", web_thread)
        self.assertIn("const known=new Set(replies.map", web_thread)
        self.assertIn("state.replies=replies", web_thread)
        self.assertIn("replaceWith(previousComposer)", html)
        self.assertIn("Boolean(result.user.following)", html)
        self.assertIn("followStateCache.set(key,Boolean(result.following))", html)
        self.assertIn("Boolean(result.user.following)", mobile)
        self.assertIn("Boolean(result.following)", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise native feed anchoring")
    def test_native_feed_anchor_only_tracks_insertions_and_expires(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        helper = "function feedInsertionAnchor(" + mobile.split(
            "function feedInsertionAnchor(", 1
        )[1].split("\n}", 1)[0] + "\n}"
        layout = mobile.split('const postCard = (post: Post) => <View key={post.id} onLayout={event => {', 1)[1].split(
            "  }} style=", 1
        )[0]
        expiry = mobile.split("    const pending = pendingFeedAnchorRef.current;\n    if (!pending) return;", 1)[1].split(
            "  }, [posts, screen, scope]);", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'), ts=require(%s);
        const anchor=new Function(ts.transpile(%s)+';return feedInsertionAnchor;')();
        const old=[{id:2},{id:1}], positions={2:100,1:250};
        assert.equal(anchor(old,old,positions),null);
        assert.equal(anchor(old,[{id:2,body:'edited'},{id:1}],positions),null);
        assert.equal(anchor(old,[...old,{id:3}],positions),null);
        assert.equal(anchor(old,[{id:1},{id:2}],positions),null);
        assert.equal(anchor(old,[{id:3},...old],{}),null);
        assert.deepEqual(anchor(old,[{id:3},...old],positions),{id:2,top:100});
        let nextFrame=0, callbacks=new Map(), scrolled=[];
        const requestAnimationFrame=fn=>{const id=++nextFrame;callbacks.set(id,fn);return id};
        const cancelAnimationFrame=id=>callbacks.delete(id);
        function frame(){const current=[...callbacks.values()];callbacks.clear();current.forEach(fn=>fn())}
        const pendingFeedAnchorRef={current:{id:2,top:100,scope:'all'}};
        const feedPostPositionsRef={current:{}},feedScrollYRef={current:300};
        const screenRef={current:'feed'},scopeRef={current:'all'},scope='all';
        const feedScrollRef={current:{scrollTo:value=>scrolled.push(value)}};
        const layout=new Function('event','post','screenRef','scopeRef','scope','feedPostPositionsRef',
          'pendingFeedAnchorRef','feedScrollYRef','feedScrollRef','requestAnimationFrame',%s);
        function layoutPost(id,top){layout({nativeEvent:{layout:{y:top}}},{id},screenRef,scopeRef,scope,
          feedPostPositionsRef,pendingFeedAnchorRef,feedScrollYRef,feedScrollRef,requestAnimationFrame)}
        layoutPost(3,10);assert.notEqual(pendingFeedAnchorRef.current,null);
        layoutPost(2,180);assert.equal(pendingFeedAnchorRef.current,null);frame();
        assert.deepEqual(scrolled,[{y:380,animated:false}]);
        pendingFeedAnchorRef.current={id:2,top:180,scope:'all'};
        const expire=new Function('pendingFeedAnchorRef','requestAnimationFrame','cancelAnimationFrame',
          'const pending=pendingFeedAnchorRef.current;if(!pending)return;'+ts.transpile(%s));
        expire(pendingFeedAnchorRef,requestAnimationFrame,cancelAnimationFrame);
        frame();assert.notEqual(pendingFeedAnchorRef.current,null);frame();
        assert.equal(pendingFeedAnchorRef.current,null);
        layoutPost(2,220);frame();assert.equal(scrolled.length,1);
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")),
               json.dumps(helper), json.dumps(layout), json.dumps(expiry))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_feed_refresh_discards_stale_responses_and_supports_menu_editing(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_poll = html.split("refreshLive = async function", 1)[1].split("startLiveRefresh();", 1)[0]
        web_inplace = html.split("refreshFeedInPlace = async function", 1)[1].split("refreshLive = async function", 1)[0]
        mobile_load = mobile.split("async function loadFeed", 1)[1].split("async function loadInbox", 1)[0]
        mobile_poll = mobile.split("const refreshVisibleScreen = async () =>", 1)[1].split(
            "const stateSubscription", 1
        )[0]
        self.assertIn("feedRequestSequence=0", html)
        self.assertIn("invalidateFeedUpdates();", html)
        self.assertIn("feedScope === requestedScope", web_poll)
        self.assertIn("requestId === feedRequestSequence", web_poll)
        self.assertIn('requestId !== feedRequestSequence || screen !== "feed" || feedScope !== requestedScope', web_inplace)
        self.assertIn("const requestId = ++feedRequestRef.current", mobile_load)
        self.assertIn("scopeRef.current !== requestedScope", mobile_load)
        self.assertIn("feedGeneration !== feedRequestRef.current", mobile_poll)
        self.assertIn("if (screen !== \"feed\")", mobile)
        self.assertIn("data-action=\"content-edit\"", html)
        self.assertIn("method: \"PATCH\", body: JSON.stringify({ body })", html)
        self.assertIn("Number(item.author.id) !== Number(me.id)", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("navigator.share", html)
        self.assertIn("This permanently deletes the reply and may also remove reposts of it and replies to those reposts.", html)
        self.assertIn('aria-label", "Remove this post as a moderator"', html)
        self.assertNotIn("Report reply", html)
        self.assertNotIn("Report reply", mobile)
        self.assertIn('accessibilityLabel={`${type === "post" ? "Post" : "Reply"} options`}', mobile)
        self.assertIn("Clipboard.setStringAsync", mobile)
        self.assertIn('await request(`/api/${target.type === "post" ? "posts" : "replies"}/${item.id}`, "PATCH", { body })', mobile)
        self.assertIn("This permanently deletes the reply and may also remove reposts of it and replies to those reposts.", mobile)
        self.assertIn("This permanently deletes the post, its replies and its uploaded media.", html)
        self.assertIn("This permanently deletes the post, its replies and its uploaded media.", mobile)
        self.assertIn("if (!await Clipboard.setStringAsync(contentText(item)))", mobile)
        self.assertIn("`Zorlii ${type} by", mobile)
        self.assertIn("Alert.alert(`Delete this ${target.type}?`", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise feed loading")
    def test_mobile_feed_loading_clears_after_silent_request_supersedes(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        load_feed = "async function loadFeed" + mobile.split(
            "async function loadFeed", 1
        )[1].split("async function loadInbox", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        const loadFeedSource=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        const transitions=[];
        const requests=[];
        const feedRequestRef={current:0},scopeRef={current:'all'},feedPollRef={current:0};
        const postsRef={current:[]},feedPostPositionsRef={},pendingFeedAnchorRef={current:null};
        const loadFeed=new Function(
          'scope','feedRequestRef','scopeRef','feedPollRef','setScope','setFeedLoading',
          'request','postsRef','feedPostPositionsRef','pendingFeedAnchorRef',
          'setPosts','feedInsertionAnchor','fail',`return (${loadFeedSource})`
        )('all',feedRequestRef,scopeRef,feedPollRef,()=>{},value=>transitions.push(value),
          ()=>new Promise(resolve=>requests.push(resolve)),postsRef,feedPostPositionsRef,
          pendingFeedAnchorRef,()=>{},()=>null,error=>{throw error});
        (async()=>{
          const first=loadFeed('all',false);
          assert.deepEqual(transitions,[true]);
          const refresh=loadFeed('all',true);
          assert.deepEqual(transitions,[true]);
          requests[0]({posts:[{id:1}]});
          await first;
          assert.deepEqual(transitions,[true]);
          requests[1]({posts:[{id:2}]});
          await refresh;
          assert.deepEqual(transitions,[true,false]);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(load_feed),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise feed updates")
    def test_feed_refresh_preserves_reply_nodes_and_selection(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        refresh = "function updateFeedPosts(newPosts) {" + html.split(
            "function updateFeedPosts(newPosts) {", 1
        )[1].split("      const originalRenderFeed", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        let contentItems={posts:{1:{id:1,body:'old'}}}, me={}, draws=0, focusCount=0;
        const file={name:'draft.png'};
        const input={isConnected:true,selectionStart:2,selectionEnd:5,selectionDirection:'forward',
          files:[file],closest(selector){return selector==='form[data-reply]'?form:null},
          focus(){focusCount++},setSelectionRange(a,b,d){this.restored=[a,b,d]}};
        const form={dataset:{reply:'1'},elements:{body:input},remove(){input.isConnected=false}};
        const card={dataset:{post:'1'},getBoundingClientRect(){return {bottom:0,top:0}}};
        const target={scrollHeight:100,querySelectorAll(selector){
          if(selector==='article.post[data-post]')return [card];
          if(selector==='form[data-reply]')return [form];
          return [];
        },querySelector(selector){
          return selector.startsWith('form[data-reply=')?{replaceWith(node){assert.equal(node,form);input.isConnected=true}}:null;
        },set innerHTML(value){draws++}};
        const document={activeElement:input,getElementById(){return target}};
        const window={scrollY:0,innerHeight:500,scrollBy(){},scrollTo(){}};
        const CSS={escape:String}, requestAnimationFrame=fn=>fn(), ensureModeratorActions=()=>{};
        function postCardsMarkup(posts){assert.equal(posts.length,1);contentItems.posts=Object.fromEntries(posts.map(p=>[p.id,p]));return ''}
        """ + refresh + """
        updateFeedPosts([{id:1,body:'old'}]);
        assert.equal(draws,0);assert.equal(input.isConnected,true);
        updateFeedPosts([{id:1,body:'new'},{id:1,body:'new'}]);
        assert.equal(draws,1);assert.equal(input.isConnected,true);assert.equal(input.files[0],file);
        assert.equal(focusCount,1);assert.deepEqual(input.restored,[2,5,'forward']);
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise periodic feed refresh")
    def test_periodic_feed_refresh_survives_notification_failure_and_rejects_stale_data(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        code = "refreshFeedInPlace = async function" + html.split(
            "refreshFeedInPlace = async function", 1
        )[1].split("      startLiveRefresh();", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        let refreshFeedInPlace,refreshLive,feedRequestSequence=0,feedScope='all',screen='feed',me={},
          activityUnreadCount=0,notificationUnreadCount=0,updates=[],resolveFeed,requests=[],delayed=false;
        const document={hidden:false},console={warn(){}},invalidateFeedUpdates=()=>feedRequestSequence++,
          originalRefreshLive=async()=>{},updateNotificationsButton=()=>{},
          updateFeedPosts=posts=>updates.push(posts);
        async function api(path){requests.push(path);if(path==='/api/notifications')throw Error('offline');
          if(delayed)return new Promise(resolve=>{resolveFeed=resolve});return {posts:[{id:2},{id:1}]}};
        """ + code + """
        (async()=>{
          await refreshLive();
          assert.deepEqual(requests,['/api/feed?scope=all','/api/notifications']);
          assert.deepEqual(updates,[[{id:2},{id:1}]]);
          delayed=true;const pending=refreshFeedInPlace();invalidateFeedUpdates();resolveFeed({posts:[{id:9}]});
          await pending;assert.equal(updates.length,1);
        })().catch(e=>{process.stderr.write(String(e));process.exitCode=1});
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise content updates")
    def test_reply_deletion_preserves_authored_quotes_and_clipboard_failure(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_remove = "function removeContentFromView(type, id, parentPostId) {" + html.split(
            "function removeContentFromView(type, id, parentPostId) {", 1
        )[1].split("    function contentEditorDialog()", 1)[0]
        mobile_filter = "function postsAfterReplyDeletion(" + mobile.split(
            "function postsAfterReplyDeletion(", 1
        )[1].split("\n}", 1)[0] + "\n}"
        mobile_copy = "async function copyContent(" + mobile.split(
            "async function copyContent(", 1
        )[1].split("\n  }", 1)[0] + "\n  }"
        script = """
        const assert=require('node:assert/strict'), ts=require(%s);
        let contentItems={posts:{1:{id:1,quoted_reply:{id:7},reposted_reply:true},
          2:{id:2,quoted_reply:{id:7},body:'my thought'},3:{id:3,body:'other'}},replies:{7:{id:7}}};
        let threadReplies={1:[{id:8}],3:[{id:7},{id:9,quoted_reply:{id:7}}]};
        const expandedReplyPosts=new Set([1]), removed=[];
        const document={querySelectorAll(selector){
          if(selector.includes('article.post[data-post="1"]'))return [{remove(){removed.push(1)}}];
          return [];
        },getElementById(){return null},querySelector(){return null}};
        const CSS={escape:String};
        """ + web_remove + """
        removeContentFromView('reply',7);
        assert.deepEqual(removed,[1]);assert.equal(contentItems.posts[1],undefined);
        assert.equal(contentItems.posts[2].body,'my thought');assert.equal(contentItems.posts[2].quoted_reply,null);
        assert.equal(threadReplies[1],undefined);assert.equal(threadReplies[3][0].quoted_reply,null);
        const helper=new Function(ts.transpile(%s)+'; return postsAfterReplyDeletion;')();
        const result=helper([{id:1,reposted_reply:true,quoted_reply:{id:7}},
          {id:2,body:'my thought',quoted_reply:{id:7}},{id:3,quoted_reply:{id:8}}],7);
        assert.deepEqual(result.map(p=>p.id),[2,3]);assert.equal(result[0].quoted_reply,null);
        assert.equal(result[1].quoted_reply.id,8);
        let copied=false, failure=null, closed=false;
        const Clipboard={setStringAsync:async()=>false}, contentText=()=>'', setContentMenu=()=>{closed=true},
          Alert={alert(){copied=true}}, fail=e=>{failure=e};
        const copy=new Function('Clipboard','contentText','setContentMenu','Alert','fail',
          ts.transpile(%s)+';return copyContent;')(Clipboard,contentText,setContentMenu,Alert,fail);
        (async()=>{await copy({});assert.equal(copied,false);assert.equal(closed,false);
          assert.match(failure.message,/Clipboard/);Clipboard.setStringAsync=async()=>true;
          await copy({});assert.equal(copied,true);assert.equal(closed,true)})().catch(e=>{console.error(e);process.exitCode=1});
        """
        script = script % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")),
                           json.dumps(mobile_filter), json.dumps(mobile_copy))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise request ordering")
    def test_web_pending_feed_render_cannot_overwrite_a_mutation(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        render = "async function renderFeed(){" + html.split("async function renderFeed(){", 1)[1].split(
            "    function contentMenuMarkup", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        let me={terms_accepted:true}, screen='feed', feedScope='all', feedRequestSequence=1, drew=false, resolve;
        const api=()=>new Promise(r=>{resolve=r}), postCardsMarkup=()=>{drew=true;return ''};
        """ + render + """
        (async()=>{const pending=renderFeed();feedRequestSequence++;resolve({posts:[{id:1}]});
          await pending;assert.equal(drew,false)})().catch(e=>{console.error(e);process.exitCode=1});
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_post_controls_keep_accessible_targets_and_compact_plus_glyphs(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('contentMenuMarkup(r,\'reply\',postId)', html)
        self.assertIn('contentMenuMarkup(p,\'post\')', html)
        self.assertIn('min-height:44px;padding:9px 11px', html)
        self.assertIn('min-height:44px;max-width:100%', html)
        self.assertIn('width:27px;height:27px;flex-basis:27px', html)
        self.assertIn('width: 44, height: 44', mobile)
        self.assertIn('fontSize: 22, lineHeight: 26', mobile)
        self.assertIn('width: 28, height: 28', mobile)
        self.assertIn('contentMenuControl(reply, "reply", parentPostId)', mobile)
        self.assertIn('contentMenu?.type === "reply" && replies[post.id]?.some(reply => reply.id === contentMenu.id)', mobile)
        self.assertIn("contentMenuActiveCard: { zIndex: 30, elevation: 4 }", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise menu accessibility")
    def test_content_menu_expanded_tracks_outside_click_and_escape(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        listeners = 'document.addEventListener("toggle"' + html.split(
            'document.addEventListener("toggle"', 1
        )[1].split('    document.addEventListener("submit", async event => {', 1)[0]
        script = """
        const assert=require('node:assert/strict'), listeners={};
        class Element {closest(){return null}}
        const summary={expanded:'true',focused:false,setAttribute(name,value){if(name==='aria-expanded')this.expanded=value},
          focus(){this.focused=true}};
        const menu={open:true,matches:()=>true,querySelector:()=>summary};
        const document={addEventListener(name,fn){listeners[name]=fn},
          querySelectorAll(){return menu.open?[menu]:[]},querySelector(){return menu.open?menu:null}};
        """ + listeners + """
        (async()=>{
          await listeners.click({target:new Element()});assert.equal(menu.open,false);assert.equal(summary.expanded,'false');
          menu.open=true;summary.expanded='true';
          listeners.keydown({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});
          assert.equal(menu.open,false);assert.equal(summary.expanded,'false');assert.equal(summary.focused,true);
          menu.open=true;listeners.toggle({target:menu});assert.equal(summary.expanded,'true');
        })().catch(e=>{console.error(e);process.exitCode=1});
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise HSL color conversion")
    def test_native_color_controls_support_full_saturation_and_lightness_range(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        match = re.search(r"function colorFromHsl\(.*?\)\s*\{(.*?)\n\}", mobile, re.S)
        self.assertIsNotNone(match)
        script = """
        const assert=require('node:assert/strict');
        const colorFromHsl=(hue,saturation,lightness)=>{%s};
        assert.equal(colorFromHsl(0,100,50),'#ff0000');
        assert.equal(colorFromHsl(0,100,25),'#800000');
        assert.equal(colorFromHsl(0,100,75),'#ff8080');
        assert.equal(colorFromHsl(0,0,50),'#808080');
        assert.equal(colorFromHsl(0,100,0),'#000000');
        assert.equal(colorFromHsl(0,100,100),'#ffffff');
        """ % match.group(1)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_visual_theme_pickers_drive_the_complete_palette_without_hex_inputs(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn('row.innerHTML = `<div class="accent-spectrum">', html)
        self.assertIn('<input type="hidden" name="theme_color" value="${color}">', html)
        self.assertIn('form.querySelectorAll(".accent-range").forEach(control => control.addEventListener("input", update))', html)
        self.assertIn("previewAccent = currentColor", html)
        for token in ("--theme-bg:", "--theme-surface:", "--theme-raised:", "--theme-input:", "--theme-border:"):
            self.assertIn(token, html)
        self.assertIn("<HueSpectrumPicker value={themeColorDraft} onChange={setThemeColorDraft} />", mobile)
        self.assertNotIn('accessibilityLabel="Accent colour hex value"', mobile)
        self.assertIn('Choose an accent with the colour picker.', html)
        self.assertIn("function colorFromHsl(hue: number, saturation: number, lightness: number)", mobile)
        for label in ('label="Hue"', 'label="Saturation"', 'label="Lightness"'):
            self.assertIn(label, mobile)
        self.assertIn("max={100}", mobile)
        self.assertIn("accessibilityRole=\"adjustable\"", mobile)
        self.assertIn("backgroundColor: palette.surface", mobile)
        self.assertIn('request("/api/settings/theme", "PATCH", { theme_color: color.toLowerCase() })', mobile)

    def test_live_suggestions_use_current_mentions_search_and_block_lists(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn('input.matches("#post-body,.replybox input[name=\'body\']")', html)
        self.assertIn("await api(`/api/search?q=${encodeURIComponent(match.query)}`)", html)
        self.assertIn("blockedUsernames.has(person.username.toLowerCase())", html)
        self.assertIn("input.setRangeText(insertion", html)
        self.assertIn("searchSequences.get(input) !== sequence", html)
        self.assertIn("composerMentionAt(key, value, selection.end)", mobile)
        composer = mobile.split("function composerMentionAt", 1)[1].split("function updateComposerText", 1)[0]
        self.assertNotIn('screen !== "feed"', composer)
        self.assertIn("setMentionTarget({ key, start, end: cursor, query: match[1] })", mobile)
        self.assertIn('request(`/api/search?q=${encodeURIComponent(mentionTarget.query)}`)', mobile)
        self.assertIn("blockedUsers.map(person => person.username.toLowerCase())", mobile)
        self.assertIn("requestId !== mentionRequestRef.current", mobile)
        self.assertIn("input?.setNativeProps({ selection })", mobile)
        self.assertIn("screen !== \"explore\" || !blockedUsersLoaded", mobile)
        self.assertIn("screen !== \"inbox\" || !token || !blockedUsersLoaded", mobile)
        self.assertIn("form.recipient, blockedUsersLoaded", mobile)
        self.assertIn('#conversation-search input[name="q"]', html)
        self.assertIn('data-action="${conversationSearch ? "message" : "suggest-account"}"', html)

    def test_moderators_can_remove_any_visible_post_without_client_side_privilege_grants(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("if (!me?.is_moderator) return;", html)
        self.assertIn('button.dataset.action = "moderation-remove-post"', html)
        self.assertIn('!button.closest("article.post[data-post]")', html)
        self.assertIn('data-action="moderation-remove-post" data-id="${r.post_id}"', html)
        self.assertIn('await api(`/api/moderation/posts/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" })', html)
        self.assertIn('me?.is_moderator ? button("Remove post", () => removeModeratedPost(post), true)', mobile)
        self.assertIn('await request(`/api/moderation/posts/${post.id}`, "DELETE")', mobile)
        self.assertIn('me?.is_moderator ? menuButton("Moderator reports"', mobile)

    def test_mini_games_receive_theme_palette_without_changing_game_state(self):
        html = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        games = (ROOT / "mobile" / "Games.tsx").read_text(encoding="utf-8")
        self.assertIn('theme={{ accent: safeAccent, accentText: themeText, surface: palette.surface, raised: palette.raised', html)
        self.assertIn("type GameTheme =", games)
        self.assertIn("theme: GameTheme", games)
        for theme_key in ("theme.surface", "theme.raised", "theme.border", "theme.accent", "theme.text", "theme.muted"):
            self.assertIn(theme_key, games)
        self.assertIn("run.state.board.flat()", games)
        self.assertIn("run.state.holds", games)

    def test_pulse_cards_do_not_show_dates_but_profiles_still_do(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        web_cards = html.split("function replyMarkup(r,postId)", 1)[1].split(
            "async function renderReport", 1
        )[0]
        web_quotes = html.split("function quotedMarkup(", 1)[1].split("function ", 1)[0]
        mobile_cards = mobile.split("const quotedContent =", 1)[1].split("function renderBody()", 1)[0]

        for cards in (web_cards, web_quotes, mobile_cards):
            self.assertNotIn("created_at", cards)
            self.assertNotIn("formatJoinedDate", cards)
        self.assertIn("formatJoinedDate(u.joined_at||u.created_at", html)
        self.assertIn("formatJoinedDate(me?.joined_at || me?.created_at", mobile)
        self.assertIn("formatJoinedDate(publicProfile.joined_at || publicProfile.created_at", mobile)
        self.assertIn("formatTimestamp(item.created_at", html)
        self.assertIn("formatTimestamp(m.created_at", html)
        self.assertIn("{item.created_at}", mobile)
        self.assertIn("formatMessageTime(message.created_at)", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise web post cards")
    def test_web_pulse_cards_render_without_author_timestamps(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        quote = "function quotedMarkup(" + html.split("function quotedMarkup(", 1)[1].split(
            "\n", 1
        )[0]
        cards = "function replyMarkup(r,postId)" + html.split("function replyMarkup(r,postId)", 1)[1].split(
            "async function renderReport", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        let contentItems={posts:{},replies:{}},me=null,expandedReplyPosts=new Set([1]),threadReplies={};
        const esc=x=>String(x??''),avatarMarkup=()=>'',profileLinkMarkup=(user,label)=>label,
          mentionMarkup=x=>x,mediaMarkup=()=>'',replyComposerMarkup=()=>'',contentMenuMarkup=()=>'',socialActionIcon=()=>'<svg></svg>';
        """ + quote + "\n" + cards + """
        const author={id:1,username:'reader',display_name:'Reader'};
        const quoted={id:3,author,created_at:'QUOTE_TIMESTAMP',body:'Quoted'};
        const reply={id:2,author,created_at:'REPLY_TIMESTAMP',body:'Reply'};
        const post={id:1,author,created_at:'POST_TIMESTAMP',body:'Post',
          reposted_by:{username:'sharer'},quoted_post:quoted,replies:[reply]};
        const output=postCardsMarkup([post]);
        for(const value of ['@reader','@sharer','Quoted','Reply']) assert.ok(output.includes(value),value);
        for(const value of ['POST_TIMESTAMP','REPLY_TIMESTAMP','QUOTE_TIMESTAMP']) assert.ok(!output.includes(value),value);
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_web_media_remove_uses_large_keyboard_accessible_hit_area(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        remove_button = html.split("function filePreviewMarkup", 1)[1].split("function replyComposerMarkup", 1)[0]

        self.assertIn(".media-preview button{position:absolute;top:0;right:0;display:grid;place-items:center;width:44px;height:44px", html)
        self.assertIn(".media-preview button:before{content:\"\";position:absolute;top:8px;right:8px;width:28px;height:28px", html)
        self.assertIn("button:focus-visible", html)
        self.assertIn('<button type="button" data-action="remove-file"', remove_button)
        self.assertIn('aria-label="Remove ${esc(file.name)}"', remove_button)
        self.assertIn("if(b.dataset.action==='remove-file')", html)

    def test_mobile_layout_respects_safe_areas_and_keyboard_scrolling(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("SafeAreaProvider, useSafeAreaInsets", mobile)
        self.assertIn("<SafeAreaProvider><AppContent /></SafeAreaProvider>", mobile)
        self.assertIn("paddingTop: 10 + insets.top", mobile)
        self.assertIn("paddingBottom: insets.bottom", mobile)
        self.assertIn('behavior={Platform.OS === "ios" ? "padding" : "height"}', mobile)
        self.assertIn('keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}', mobile)
        self.assertIn("automaticallyAdjustKeyboardInsets={Platform.OS === \"ios\"}", mobile)
        self.assertNotIn("paddingTop: Platform.OS === \"ios\" ? 57 : 28", mobile)

    def test_web_mentions_are_escaped_linked_and_use_registered_username_boundaries(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_]{3,24})(?![A-Za-z0-9_])", html)
        self.assertIn("function mentionMarkup(text)", html)
        self.assertIn("profileLinkMarkup(match[1]", html)
        self.assertIn("function profileLinkMarkup(username,label", html)
        self.assertIn("await renderPublicProfile(b.dataset.profile)", html)
        self.assertIn("${mentionMarkup(p.body)}", html)
        self.assertIn("${mentionMarkup(r.body)}", html)
        self.assertIn("'mention-link'", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise the web JavaScript")
    def test_hashtag_links_escape_text_and_preserve_mentions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        lines = html.splitlines()
        code = "\n".join(next(line for line in lines if marker in line) for marker in (
            "const esc=s=>", "function profileLinkMarkup(", "function mentionMarkup(",
        ))
        script = code + """
        const assert = require('node:assert/strict');
        const result = mentionMarkup('<b> @alice #Music! #Café #musical foo#music ##music');
        assert.match(result, /&lt;b&gt;/);
        assert.match(result, /data-profile="alice"/);
        assert.match(result, /data-hashtag="Music"/);
        assert.match(result, /data-hashtag="Café"/);
        assert.equal((result.match(/data-hashtag=/g) || []).length, 3);
        """
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, encoding="utf-8")

    def test_follower_links_open_the_selected_members_list(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('data-action="member-list" data-kind="followers" data-user="${esc(u.username)}"', html)
        self.assertIn('data-action="member-list" data-kind="following" data-user="${esc(u.username)}"', html)
        self.assertIn('openSocialList(publicProfile.username, "followers")', mobile)
        self.assertIn('openSocialList(publicProfile.username, "following")', mobile)
        self.assertIn("people.length < socialList.count", mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise the mobile tag pattern")
    def test_mobile_tag_pattern_keeps_mentions_and_hashtag_boundaries(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        pattern = next(line for line in mobile.splitlines() if "const mentionPattern =" in line)
        script = pattern + """
        const assert = require('node:assert/strict');
        const tokens = [...'@alice #Music! #Café foo#music ##music'.matchAll(mentionPattern)]
          .map(match => match[2] ? '@' + match[2] : '#' + match[4]);
        assert.deepEqual(tokens, ['@alice', '#Music', '#Café']);
        """
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, encoding="utf-8")

    def test_web_conversation_history_paginates_without_losing_loaded_messages(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/conversations/${id}/messages?before_id=${encodeURIComponent(oldestId)}", html)
        self.assertIn("function mergeConversationMessages(current,incoming)", html)
        self.assertIn("state.messages=mergeConversationMessages(state.messages,d.messages)", html)
        self.assertIn("state.messages=mergeConversationMessages(d.messages,state.messages)", html)
        self.assertIn("if(!existing){state.hasMore=Boolean(d.has_more)", html)
        self.assertIn("data-action=\"load-older\"", html)
        self.assertIn("d.conversation_created_at", html)
        self.assertIn("formatConversationDate(c.created_at)", html)
        self.assertIn("formatTimestamp(m.created_at,{timeStyle:'short'})", html)
        self.assertIn("function parseTimestamp(value)", html)
        self.assertIn("text+='Z'", html)
        self.assertIn("new Intl.DateTimeFormat(undefined,options).format(date)", html)

    def test_conversation_screen_has_accessible_send_and_independent_scroll(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        panel = html.split("async function openConversation", 1)[1].split(
            "async function loadOlderMessages", 1
        )[0]
        native = mobile.split('if (screen === "messages") {', 1)[1].split(
            'if (screen === "profile")', 1
        )[0]
        self.assertIn('aria-label="Back to inbox"', panel)
        self.assertIn('class="arrow-submit" aria-label="Send message"', panel)
        self.assertIn('class="messages" role="log"', panel)
        self.assertIn("if(preserveScroll&&oldBox)", panel)
        self.assertIn("window.visualViewport?.addEventListener('resize',sizeConversationViewport)", html)
        self.assertIn("#conversation-view .conversation-panel{position:fixed", html)
        self.assertIn("#conversation-view .messages{flex:1 1 0;min-height:0", html)
        self.assertIn("env(safe-area-inset-bottom)", html)
        self.assertIn('accessibilityLabel="Back to inbox"', native)
        self.assertIn('accessibilityLabel="Send message"', native)
        self.assertIn("ref={messageScrollRef}", native)
        self.assertIn("loadOlderMessages()", native)
        self.assertIn('screen === "messages" ? <View style={[styles.conversationScreen', mobile)
        self.assertIn("paddingBottom: Math.max(insets.bottom, 8)", mobile)
        self.assertIn("messageList: { flex: 1, minHeight: 0", mobile)
        self.assertIn("messageDraftsRef.current[conversationId] = value", native)
        self.assertIn('BackHandler.addEventListener("hardwareBackPress"', mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise conversation navigation")
    def test_web_conversation_back_escape_restore_focus_draft_and_scroll(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        close = "function closeConversation()" + html.split(
            "function closeConversation()", 1
        )[1].split("function requestConversationClose", 1)[0]
        request_close = "function requestConversationClose()" + html.split(
            "function requestConversationClose()", 1
        )[1].split("function handleConversationEscape", 1)[0]
        escape = "function handleConversationEscape(event)" + html.split(
            "function handleConversationEscape(event)", 1
        )[1].split("function handleConversationPopstate", 1)[0]
        popstate = "function handleConversationPopstate(event)" + html.split(
            "function handleConversationPopstate(event)", 1
        )[1].split("function sizeConversationViewport", 1)[0]
        opening = html.split("async function openConversation", 1)[1].split(
            "async function loadOlderMessages", 1
        )[0]
        self.assertIn("history.pushState({...history.state,zorliiConversation:id}", opening)
        self.assertIn("conversationDrafts.get(id)||''", opening)
        self.assertIn("window.addEventListener('popstate',handleConversationPopstate)", html)
        self.assertIn("document.addEventListener('keydown',handleConversationEscape)", html)
        self.assertIn("if(b.dataset.action==='conversation-back'){requestConversationClose();return}", html)
        self.assertIn("#conversation-view .conversation-start{display:none}", html)
        self.assertIn("#conversation-view .conversation-head{min-height:44px", html)
        self.assertIn(".main:has(#conversation-search)>.eyebrow:first-child{padding-left:0!important}", html)
        self.assertIn("#conversation-view .message-composer{position:static", html)
        self.assertIn("padding:10px 0 max(16px,env(safe-area-inset-bottom))", html)
        self.assertIn('<div class="message-meta">', html)
        self.assertIn("m.sender_id===me?.id?'':profileLinkMarkup", html)
        self.assertIn("#conversation-search{display:flex;align-items:center", html)

        script = """
        const assert=require('node:assert/strict');
        const [close,requestClose,escape,popstate]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        function harness(){
          let panel={dataset:{id:'17'},querySelector:selector=>selector.includes('[name="body"]')?field:null};
          const field={value:'unfinished synthetic draft'},opener={isConnected:true,focus:()=>{focused='opener'}};
          const inboxTitle={focus:()=>{focused='inbox title'}};
          const target={querySelector:selector=>selector==='.conversation-panel'?panel:null,replaceChildren:()=>{panel=null}};
          let focused='',scroll=0;
          let screen='inbox',threadReturnView=null,backCount=0,openCalls=[],inertCalls=[];
          const conversationDrafts=new Map(),document={getElementById:id=>id==='conversation-view'?target:id==='inbox-title'?inboxTitle:null};
          const window={scrollTo:(x,y)=>{scroll=y}},history={state:{zorliiConversation:17},back:()=>{}};
          const ui=new Function('document','window','history','opener','setConversationBackgroundInert','openConversation','restoreThreadReturnView',
            `let activeConversation=17,conversationDrafts=new Map(),conversationReturnFocus=opener,conversationReturnScroll=223,screen='inbox',threadReturnView=null;${close}${requestClose}${escape}${popstate};return {closeConversation,requestConversationClose,handleConversationEscape,handleConversationPopstate,get active(){return activeConversation},set active(value){activeConversation=value},get drafts(){return conversationDrafts}}`)(
            document,window,history,opener,(target,enabled)=>inertCalls.push(enabled),(id,options)=>openCalls.push([id,options]),()=>{});
          history.back=()=>{backCount++;history.state=null;ui.handleConversationPopstate({state:null})};
          return {ui,history,field,opener,get panel(){return panel},get focused(){return focused},get scroll(){return scroll},
            get backCount(){return backCount},openCalls,inertCalls};
        }
        let h=harness(),prevented=0,stopped=0;
        h.ui.handleConversationEscape({key:'Escape',preventDefault:()=>prevented++,stopImmediatePropagation:()=>stopped++});
        assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(h.backCount,1);
        assert.equal(h.ui.active,null);assert.equal(h.panel,null);assert.equal(h.ui.drafts.get(17),'unfinished synthetic draft');
        assert.equal(h.focused,'opener');assert.equal(h.scroll,223);assert.deepEqual(h.inertCalls,[false]);
        h=harness();h.ui.handleConversationEscape({key:'Tab',preventDefault(){throw Error('unexpected preventDefault')},stopImmediatePropagation(){throw Error('unexpected stop')}});
        h.history.state=null;h.ui.requestConversationClose();assert.equal(h.backCount,0);assert.equal(h.ui.active,null);
        h=harness();h.ui.active=null;h.ui.handleConversationPopstate({state:{zorliiConversation:17}});
        assert.deepEqual(h.openCalls,[[17,{historyEntry:true}]]);
        """
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps([close, request_close, escape, popstate]),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise message pagination")
    def test_older_messages_preserve_scroll_and_release_loading_when_closed(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        older = "async function loadOlderMessages" + html.split(
            "async function loadOlderMessages", 1
        )[1].split("async function refresh()", 1)[0]
        merge = "function mergeConversationMessages" + html.split(
            "function mergeConversationMessages", 1
        )[1].split("let conversationReturnFocus", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        const [mergeSource,olderSource]=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
        const mergeConversationMessages=new Function(`${mergeSource};return mergeConversationMessages`)();
        const state={id:1,messages:[{id:2},{id:3}],hasMore:true,loading:false},conversationStates=new Map([[1,state]]);
        let activeConversation=1,resolve,box={scrollHeight:100,scrollTop:20,innerHTML:'',querySelector:()=>null};
        const document={querySelector:()=>box},toast=error=>{throw Error(error)};
        const api=()=>new Promise(r=>resolve=r);
        const conversationMessagesMarkup=()=>{box.scrollHeight=180;return 'messages'};
        const load=new Function('conversationStates','getActive','document','api','mergeConversationMessages','conversationMessagesMarkup','toast',
          `return (${olderSource.replaceAll('activeConversation','getActive()')})`)(conversationStates,()=>activeConversation,document,api,mergeConversationMessages,conversationMessagesMarkup,toast);
        (async()=>{
          const first=load(1);resolve({messages:[{id:1}],has_more:true});await first;
          assert.deepEqual(state.messages.map(x=>x.id),[1,2,3]);assert.equal(box.scrollTop,100);assert.equal(state.loading,false);
          const pending=load(1);activeConversation=null;resolve({messages:[],has_more:false});await pending;
          assert.equal(state.loading,false);assert.equal(state.hasMore,true);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps([merge, older]),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_web_profile_keeps_activity_visible_and_groups_utilities(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        profile = html.split("async function renderProfile()", 1)[1].split(
            "async function renderProfilePosts", 1
        )[0]
        profile_view = html.split("async function renderProfile()", 1)[1].split(
            "async function renderSettings", 1
        )[0]

        self.assertNotIn("u.email", profile)
        self.assertIn('class="avatar-plus" data-action="avatar-pick" aria-label="Upload profile photo"', profile)
        self.assertIn('id="profile-posts"', profile)
        self.assertIn('data-go="social-followers"', profile)
        self.assertIn('data-go="social-following"', profile)
        self.assertNotIn("name=\"bio\"", profile_view)
        self.assertIn('data-go="settings"', html)
        settings = html.split("async function renderSettings()", 1)[1].split(
            "async function renderProfilePosts", 1
        )[0]
        self.assertIn('id="profile-form"', settings)
        self.assertIn("name=\"bio\"", settings)
        feed = html.split("async function renderFeed", 1)[1].split("function replyMarkup", 1)[0]
        self.assertIn('<span aria-hidden="true">+</span>', feed)
        self.assertIn("Privacy &amp; local tools", settings)
        self.assertIn("Local context &amp; help", settings)
        self.assertIn("Community safety", settings)
        self.assertIn("`/api/users/${encodeURIComponent(state.username)}/posts`", html)
        self.assertIn('data-action="zoom-media"', html)
        self.assertIn("class=\"post-media\"", html)

    def test_phone_profile_reserves_drawer_space_and_compacts_activity_summary(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn(".main>.eyebrow:first-child{display:flex;align-items:center;min-height:44px;padding-left:52px}", html)
        self.assertIn(".activity-counts{grid-template-columns:repeat(4,minmax(0,1fr))", html)
        self.assertIn(".nav button,.sidebar .nav button{font-size:12px}", html)
        profile = mobile.split('if (screen === "profile") return', 1)[1].split(
            'if (screen === "settings") return', 1
        )[0]
        self.assertIn('<View style={styles.activityGrid}>', profile)
        self.assertIn("styles.activityMetric", profile)

    def test_web_mention_activities_link_to_the_mentioned_post(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        notification = html.split("function notificationDescription(item)", 1)[1].split(
            "async function renderNotifications", 1
        )[0]

        self.assertIn("item.kind==='mention'", notification)
        self.assertIn("mentioned you in a", notification)
        self.assertIn('data-action="open-mentioned-post"', notification)
        self.assertIn("data-post=\"${esc(item.post_id)}\"", notification)
        self.assertIn("await renderMentionedPost(b.dataset.post,b.dataset.reply)", html)
        self.assertIn("function renderMentionedPost(postId,replyId)", html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise the web JavaScript")
    def test_profile_totals_and_incremental_post_loading(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        lines = html.splitlines()
        counts = next(line for line in lines if "function activityCountsMarkup(" in line)
        loader = next(line for line in lines if "async function loadProfilePosts(" in line)
        cards = html.split("    function postCardsMarkup(posts,append=false){", 1)[1].split(
            "    async function renderReport()", 1
        )[0]
        script = """
        const assert = require('node:assert/strict');
        let contentItems={posts:{},replies:{}}, me=null, expandedReplyPosts=new Set(), threadReplies={};
        const esc=x=>String(x??''), avatarMarkup=()=>'', profileLinkMarkup=()=>'', mentionMarkup=()=>'', mediaMarkup=()=>'', quotedMarkup=()=>'', echoMenuMarkup=()=>'', contentMenuMarkup=()=>'', replyMarkup=()=>'', replyComposerMarkup=()=>'', toast=()=>{};
        function postCardsMarkup(posts,append=false){
        """ + cards + "\n" + counts + "\n" + loader + """
        const makePost=id=>({id,author:{username:'person',display_name:'Person'},created_at:'today'});
        const markup=activityCountsMarkup({posts:45,media:3,replies:0,likes:12,echoes:5,saved:9,messages:23});
        for(const count of ['45','3','0','12','5','9','23']) assert.match(markup,new RegExp('>'+count+'</strong>'));
        assert.match(markup,/>Saved</);assert.match(markup,/>Messages sent</);
        assert.match(activityCountsMarkup(null),/>—<\\/strong>/);
        const list={html:'',insertAdjacentHTML(where,html){this.html+=html}};
        const pagination={innerHTML:''};
        let button={disabled:false,textContent:''};
        const target={id:'profile-posts',profilePagination:{username:'person',posts:[],hasMore:false,loading:false},className:'',
          set innerHTML(value){this.html=value;list.html=value},get innerHTML(){return this.html},
          querySelector(selector){return selector==='.profile-post-list'?list:selector==='.profile-post-pagination'?pagination:button}};
        const document={getElementById:()=>target};
        const requests=[];
        const pages=[{posts:[makePost(5),makePost(4)],has_more:true},new Error('offline'),
          {posts:[makePost(3),makePost(2)],has_more:true},{posts:[makePost(1)],has_more:false}];
        async function api(path){requests.push(path);const page=pages.shift();if(page instanceof Error)throw page;return page}
        (async()=>{
          await loadProfilePosts(target,true);
          const first=list.html;
          assert.match(pagination.innerHTML,/Load older posts/);
          await loadProfilePosts(target);
          assert.equal(list.html,first);assert.equal(target.profilePagination.posts.length,2);
          assert.equal(button.disabled,false);
          await loadProfilePosts(target);
          assert.ok(list.html.startsWith(first));
          assert.deepEqual(target.profilePagination.posts.map(p=>p.id),[5,4,3,2]);
          assert.deepEqual(Object.keys(contentItems.posts),['2','3','4','5']);
          await loadProfilePosts(target);
          assert.deepEqual(target.profilePagination.posts.map(p=>p.id),[5,4,3,2,1]);
          assert.equal(pagination.innerHTML,'');
          await loadProfilePosts(target);
          assert.deepEqual(requests,['/api/users/person/posts','/api/users/person/posts?before_id=4',
            '/api/users/person/posts?before_id=4','/api/users/person/posts?before_id=2']);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise web drawer state")
    def test_web_drawer_open_state_updates_accessibility_and_focus(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        web_script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        drawer_function = web_script.split("function setDrawerOpen", 1)[1].split(
            "function drawerMarkup", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        const makeClassList=()=>{const values=new Set();return {
          toggle(name,force){const open=force??!values.has(name);open?values.add(name):values.delete(name);return open},
          contains(name){return values.has(name)}
        }};
        const attrs={};let focused='';
        const first={focus(){focused='first'}},toggle={focus(){focused='toggle'},setAttribute(name,value){attrs[`toggle-${name}`]=value}};
        const drawer={classList:makeClassList(),setAttribute(name,value){attrs[name]=value},
          querySelector(){return first},inert:true};
        const scrim={classList:makeClassList()};
        const document={getElementById:id=>id==='app-drawer'?drawer:scrim,querySelector:()=>toggle};
        """ + "function setDrawerOpen" + drawer_function + """
        setDrawerOpen(true);
        assert.equal(drawer.classList.contains('open'),true);
        assert.equal(scrim.classList.contains('open'),true);
        assert.equal(attrs['aria-hidden'],'false');
        assert.equal(drawer.inert,false);
        assert.equal(attrs['toggle-aria-expanded'],'true');
        assert.equal(focused,'first');
        setDrawerOpen(false);
        assert.equal(drawer.classList.contains('open'),false);
        assert.equal(scrim.classList.contains('open'),false);
        assert.equal(attrs['aria-hidden'],'true');
        assert.equal(drawer.inert,true);
        assert.equal(attrs['toggle-aria-expanded'],'false');
        assert.equal(focused,'toggle');
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise web date formatting")
    def test_joined_dates_use_viewer_language_and_omit_invalid_values(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        web_script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        date_helpers = web_script.split("function parseTimestamp", 1)[1].split(
            "function normalizedHex", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        """ + "function parseTimestamp" + date_helpers + """
        assert.equal(formatJoinedDate('2026-06-23T00:00:00Z'),'Joined 23rd June, 2026');
        assert.equal(formatJoinedDate('2026-06-01'),'Joined 1st June, 2026');
        assert.equal(formatJoinedDate('2026-06-02'),'Joined 2nd June, 2026');
        assert.equal(formatJoinedDate('2026-06-11'),'Joined 11th June, 2026');
        const date=new Date('2026-06-23T00:00:00Z');
        for(const [language,prefix,suffix] of [
          ['fr-FR','Membre depuis le ', ''],
          ['es-ES','Se unió el ', ''],
          ['ar','انضم في ', ''],
          ['hi-IN','', ' को शामिल हुए'],
          ['ur','شمولیت: ', ''],
        ]){
          const formatted=new Intl.DateTimeFormat(language,{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(date);
          assert.equal(formatJoinedDate('2026-06-23T02:00:00+02:00',language),prefix+formatted+suffix);
        }
        assert.throws(()=>formatJoinedDate('2026-06-23','invalid'),/Unsupported language/);
        assert.equal(formatJoinedDate(''), '');
        assert.equal(formatJoinedDate('not-a-date'), '');
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function formatJoinedDate(value?: string | null, language = \"en-US\")", mobile)
        self.assertIn("formatJoinedDate(me?.joined_at || me?.created_at, me?.language)", mobile)
        self.assertIn("formatJoinedDate(publicProfile.joined_at || publicProfile.created_at, me?.language)", mobile)
        self.assertIn("formatJoinedDate(u.joined_at||u.created_at,me?.language)", html)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed to exercise mobile date formatting")
    def test_mobile_joined_dates_match_web_for_each_language(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile_helper = "function formatJoinedDate" + mobile.split("function formatJoinedDate", 1)[1].split(
            "\nfunction PostVideo", 1
        )[0]
        web_script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        web_helpers = "function parseTimestamp" + web_script.split("function parseTimestamp", 1)[1].split(
            "function normalizedHex", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        const ts=require(%s);
        const mobileSource=%s;
        const mobile=new Function(ts.transpile(mobileSource)+'; return formatJoinedDate;')();
        const web=new Function(%s+'; return formatJoinedDate;')();
        for(const locale of ['en-US','fr-FR','es-ES','ar','hi-IN','ur']){
          for(const date of ['2026-06-23T02:00:00+02:00','2026-06-01','','not-a-date']){
            assert.equal(mobile(date,locale),web(date,locale),locale+' '+date);
          }
        }
        assert.throws(()=>mobile('2026-06-23','invalid'),/Unsupported language/);
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")),
               json.dumps(mobile_helper), json.dumps(web_helpers))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise web theme synchronization")
    def test_theme_sync_merges_account_fields_and_keeps_extreme_accents_readable(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        web_script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        theme_helpers = web_script.split("function normalizedHex", 1)[1].split(
            "function drawerMarkup", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        let me={username:'reader',bio:'kept',display_name:'Reader'};
        const vars={},nodes={};
        const document={
          documentElement:{style:{setProperty(name,value){vars[name]=value}}},
          getElementById:id=>nodes[id]||null,
          createElement:()=>({}),
          head:{appendChild(node){nodes[node.id]=node}}
        };
        """ + "function normalizedHex" + theme_helpers + """
        updateMe({theme_color:'#000000'});
        assert.equal(me.bio,'kept');
        assert.equal(me.username,'reader');
        assert.equal(vars['--accent-ink'],'#11111b');
        assert.notEqual(vars['--accent-ui'],'#000000');
        assert.match(nodes['account-theme-styles'].textContent,/var\\(--accent-ui\\)/);
        updateMe({theme_color:'#ffffff'});
        assert.equal(vars['--accent-ink'],'#11111b');
        assert.equal(vars['--accent'],'#ffffff');
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("setMe(current => current ? { ...current, ...user } as User : user as User)", mobile)
        self.assertIn('request("/api/settings/theme", "PATCH", { theme_color: color.toLowerCase() })', mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise personalized palette contrast")
    def test_personalized_palette_text_and_accents_keep_wcag_contrast(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        native_helpers = []
        for pattern in (
            r"function colorLuminance\(color: string\) \{.*?\n\}",
            r"function contrastForeground\(color: string\) \{[^\n]*\}",
            r"function readableAccent\(color: string\) \{.*?\n\}",
            r"function mixColor\(color: string, base: string, amount: number\) \{.*?\n\}",
        ):
            match = re.search(pattern, mobile, re.S)
            self.assertIsNotNone(match, pattern)
            native_helpers.append(
                match.group(0)
                .replace("color: string", "color")
                .replace("base: string", "base")
                .replace("amount: number", "amount")
            )

        web_helpers = html.split("function accentForeground", 1)[1].split(
            "function hslFromHex", 1
        )[0]
        web_helpers = "function accentForeground" + web_helpers
        web_helpers = web_helpers.replace(
            "function accentForeground(hex)", "function accentForeground(hex)"
        )
        script = """
        const assert=require('node:assert/strict');
        const ratio=(foreground,background)=>{
          const luminance=color=>{
            const channels=color.slice(1).match(/.{2}/g).map(part=>parseInt(part,16)/255)
              .map(channel=>channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4);
            return .2126*channels[0]+.7152*channels[1]+.0722*channels[2];
          };
          const values=[luminance(foreground),luminance(background)].sort((a,b)=>b-a);
          return (values[0]+.05)/(values[1]+.05);
        };
        """ + "\n".join(native_helpers) + """
        const accents=['#000000','#ffffff','#00ff40','#ff00ff','#00ffff'];
        for(const accent of accents){
          const safe=readableAccent(accent), text=contrastForeground(safe);
          const surfaces=[
            mixColor(accent,'#080a16',.18),
            mixColor(accent,'#101329',.24),
            mixColor(accent,'#17182e',.30),
            mixColor(accent,'#0b0d1d',.16)
          ];
          for(const surface of surfaces){
            for(const normal of ['#f5f2ff','#e7e1eb','#eee7f8','#ece8f7']){
              assert.ok(ratio(normal,surface)>=4.5,`native normal text ${normal} ${accent} ${surface}`);
            }
            assert.ok(ratio('#e5e2ee',surface)>=4.5,`native muted text ${accent} ${surface}`);
            assert.ok(ratio(safe,surface)>=4.5,`native accent ${accent} ${surface}`);
          }
          const tabSurface=mixColor(accent,'#101329',.24);
          assert.ok(ratio('#d7bcff',tabSurface)>=4.5,`native active tab icon ${accent}`);
          assert.ok(ratio(text,safe)>=4.5,`native accent foreground ${accent}`);
        }
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

        web_accent_functions = re.search(
            r"function accentForeground\(hex\).*?function hslFromHex", html, re.S
        )
        self.assertIsNotNone(web_accent_functions)
        web_accent_functions = web_accent_functions.group(0).rsplit("function hslFromHex", 1)[0]
        web_script = """
        const assert=require('node:assert/strict');
        const ratio=(foreground,background)=>{
          const luminance=color=>{
            const channels=color.slice(1).match(/.{2}/g).map(part=>parseInt(part,16)/255)
              .map(channel=>channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4);
            return .2126*channels[0]+.7152*channels[1]+.0722*channels[2];
          };
          const values=[luminance(foreground),luminance(background)].sort((a,b)=>b-a);
          return (values[0]+.05)/(values[1]+.05);
        };
        """ + web_accent_functions + """
        for(const accent of ['#000000','#ffffff','#00ff40','#ff00ff','#00ffff']){
          const safe=accentReadable(accent);
          const surfaces=[
            '#080a16','#101329','#17182e','#0b0d1d'
          ].map((base,index)=>{
            const amount=[.16,.22,.28,.14][index];
            const a=accent.slice(1).match(/.{2}/g).map(part=>parseInt(part,16));
            const b=base.slice(1).match(/.{2}/g).map(part=>parseInt(part,16));
            return '#'+a.map((value,i)=>Math.round(b[i]+(value-b[i])*amount).toString(16).padStart(2,'0')).join('');
          });
          for(const surface of surfaces){
            assert.ok(ratio('#e5e2ee',surface)>=4.5,`web muted text ${accent} ${surface}`);
            for(const normal of ['#f1efff','#f4f1ff','#ece8f7']){
              assert.ok(ratio(normal,surface)>=4.5,`web normal text ${normal} ${accent} ${surface}`);
            }
            assert.ok(ratio(safe,surface)>=4.5,`web accent ${accent} ${surface}`);
          }
          assert.ok(ratio(accentForeground(safe),safe)>=4.5,`web accent foreground ${accent}`);
        }
        """
        result = subprocess.run(["node", "-e", web_script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(":root{--muted:#e5e2ee;--theme-muted:#e5e2ee", html)
        self.assertIn("input::placeholder,textarea::placeholder{color:var(--theme-muted)!important;opacity:1}", html)
        self.assertIn("placeholderTextColor={palette.muted}", mobile)
        self.assertIn('muted: "#e5e2ee"', mobile)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise web theme validation")
    def test_theme_save_rejects_bad_hex_and_propagates_server_errors(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        web_script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        normalizer = web_script.split("function normalizedHex", 1)[1].split(
            "function accentForeground", 1
        )[0]
        save_helper = web_script.split("async function saveThemePreference", 1)[1].split(
            "function setDrawerOpen", 1
        )[0]
        script = """
        const assert=require('node:assert/strict');
        let calls=[],updated=null,api=async(path,options)=>{calls.push([path,options]);return {user:{theme_color:'#abcdef'}}};
        function updateMe(user){updated=user}
        """ + "function normalizedHex" + normalizer + "async function saveThemePreference" + save_helper + """
        (async()=>{
          await assert.rejects(saveThemePreference('#abc'),/valid hex colour/);
          assert.equal(calls.length,0);
          const user=await saveThemePreference('#ABCDEF');
          assert.equal(calls[0][0],'/api/settings/theme');
          assert.equal(JSON.parse(calls[0][1].body).theme_color,'#abcdef');
          assert.equal(updated,user);
          api=async()=>{throw new Error('offline')};
          await assert.rejects(saveThemePreference('#ffffff'),/offline/);
          assert.match('catch(err){toast(err.message)}',/toast\\(err.message\\)/);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('catch(err){toast(err.message)}', web_script)
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('if (!validHexColor(color)) { setError("Enter a six-digit hex colour', mobile)
        self.assertIn('const result = await request("/api/settings/theme", "PATCH"', mobile)
        self.assertIn("} catch (e) { fail(e); }", mobile)

    def test_mobile_screen_transitions_and_modals_respect_reduce_motion(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        update_me = mobile.split("function updateMe(", 1)[1].split("async function request", 1)[0]
        self.assertIn("AccessibilityInfo.isReduceMotionEnabled()", mobile)
        self.assertIn('AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion)', mobile)
        self.assertNotIn("useEffect", update_me.split("  useEffect", 1)[0])
        self.assertIn("if (reduceMotion) {\n      screenOpacity.setValue(1);\n      screenOffset.setValue(0);", mobile)
        self.assertIn("Animated.timing(screenOpacity, { toValue: 1, duration: 150", mobile)
        self.assertGreaterEqual(mobile.count('animationType={reduceMotion ? "none" : "fade"}'), 2)
        self.assertIn("if (reduceMotion) {\n      menuTranslateX.setValue(0);\n      menuScrimOpacity.setValue(1);", mobile)
        self.assertIn("buttonPressedReduced: { opacity: 0.86 }", mobile)


if __name__ == "__main__":
    unittest.main()
