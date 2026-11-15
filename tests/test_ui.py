import re
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from zorlii_app.db import Database
from zorlii_app.main import new_app


ROOT = Path(__file__).resolve().parents[1]


class WebUiRegressionTests(unittest.TestCase):
    def test_registration_inputs_share_full_width_mobile_rule(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        registration = html.split("function authScreen", 1)[1].split("function", 1)[0]
        for field in ("display_name", "username", "email", "password"):
            self.assertRegex(registration, rf'<input type="(?:text|email|password)" name="{field}"')
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
        self.assertIn("button.dataset.go = \"notifications\"", html)
        self.assertIn("<h1>Activities</h1>", html)
        self.assertIn("/api/notifications/read", html)
        self.assertIn("/followers?limit=1", html)
        self.assertIn("/following?limit=1", html)
        self.assertIn("renderSocialList(kind)", html)
        self.assertIn('data-go="social-followers"', html)
        self.assertIn('data-go="social-following"', html)
        self.assertIn("4–128 characters", mobile)
        self.assertIn('"/api/notifications"', mobile)
        self.assertIn('"/api/notifications/read"', mobile)
        self.assertIn("/followers", mobile)
        self.assertIn("/following", mobile)

    def test_mobile_push_registration_and_notification_handling(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        app_json = (ROOT / "mobile" / "app.json").read_text(encoding="utf-8")
        app_config = (ROOT / "mobile" / "app.config.js").read_text(encoding="utf-8")
        self.assertIn("getExpoPushTokenAsync({ projectId })", mobile)
        self.assertIn('"/api/push-token"', mobile)
        self.assertIn("addNotificationResponseReceivedListener", mobile)
        self.assertIn('"expo-notifications"', app_json)
        self.assertIn("EXPO_PUBLIC_EAS_PROJECT_ID", app_config)

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
        self.assertIn("grid-template-columns:repeat(6,minmax(0,1fr))", html)
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
        self.assertIn('["feed", "explore", "create", "inbox", "notifications", "profile"]', mobile)
        self.assertIn("composerRef.current?.focus()", mobile)
        self.assertIn("Privacy &amp; local tools", html)
        self.assertIn("Privacy & local tools", mobile)

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
        self.assertNotIn('data-action="repost"', web_cards)
        self.assertNotIn('data-action="quote"', web_cards)
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
        self.assertIn(".nav button.active{background:#8b35ff2c", mobile_styles)
        self.assertIn(".nav button[data-action=\"create-post\"] .nav-symbol{background:linear-gradient", mobile_styles)
        self.assertNotIn("background:linear-gradient(160deg,#11131f", mobile_styles)
        self.assertNotIn(".nav button.active{background:#302c39", mobile_styles)

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
        self.assertIn('<span aria-hidden="true">▧</span>', html)
        self.assertIn('label="Attach photos, videos, or GIFs to post"', mobile)
        self.assertIn('label="Attach photos, videos, or GIFs to reply"', mobile)
        self.assertIn("mediaPickerButton:", mobile)
        self.assertIn("style={[styles.mediaPickerIcon, { color: readableAccent(activeThemeAccent) }]} accessibilityElementsHidden", mobile)
        self.assertIn("accessibilityElementsHidden>+</Text>", mobile)

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

        self.assertIn(
            r"/(?<![A-Za-z0-9_@.])@([A-Za-z0-9_]{3,24})(?![A-Za-z0-9_])/gi",
            html,
        )
        self.assertIn("function mentionMarkup(text)", html)
        self.assertIn("profileLinkMarkup(match[1]", html)
        self.assertIn("function profileLinkMarkup(username,label", html)
        self.assertIn("await renderPublicProfile(b.dataset.profile)", html)
        self.assertIn("${mentionMarkup(p.body)}", html)
        self.assertIn("${mentionMarkup(r.body)}", html)
        self.assertIn("'mention-link'", html)

    def test_web_conversation_history_paginates_without_losing_loaded_messages(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/conversations/${id}/messages?before_id=${encodeURIComponent(oldestId)}", html)
        self.assertIn("function mergeConversationMessages(current,incoming)", html)
        self.assertIn("state.messages=mergeConversationMessages(state.messages,d.messages)", html)
        self.assertIn("state.messages=mergeConversationMessages(d.messages,state.messages)", html)
        self.assertIn("if(!existing)state.hasMore=Boolean(d.has_more)", html)
        self.assertIn("data-action=\"load-older\"", html)
        self.assertIn("d.conversation_created_at", html)
        self.assertIn("formatConversationDate(c.created_at)", html)
        self.assertIn("formatTimestamp(m.created_at,{timeStyle:'short'})", html)
        self.assertIn("function parseTimestamp(value)", html)
        self.assertIn("text+='Z'", html)
        self.assertIn("new Intl.DateTimeFormat(undefined,options).format(date)", html)

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
        const esc=x=>String(x??''), avatarMarkup=()=>'', profileLinkMarkup=()=>'', mentionMarkup=()=>'', mediaMarkup=()=>'', quotedMarkup=()=>'', echoMenuMarkup=()=>'', replyMarkup=()=>'', replyComposerMarkup=()=>'', toast=()=>{};
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
    def test_joined_dates_use_ordinals_and_omit_missing_or_invalid_values(self):
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
        assert.equal(formatJoinedDate(''), '');
        assert.equal(formatJoinedDate('not-a-date'), '');
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function formatJoinedDate(value?: string | null)", mobile)
        self.assertIn("formatJoinedDate(me?.joined_at || me?.created_at)", mobile)
        self.assertIn("formatJoinedDate(publicProfile.joined_at || publicProfile.created_at)", mobile)

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
        self.assertGreaterEqual(mobile.count('animationType={reduceMotion ? "none" : "fade"}'), 3)
        self.assertIn("buttonPressedReduced: { opacity: 0.86 }", mobile)


if __name__ == "__main__":
    unittest.main()
