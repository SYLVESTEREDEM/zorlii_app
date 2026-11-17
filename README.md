# Zorlii

Zorlii is a persistent, small-community social MVP: FastAPI + SQLite API, a branded web client, and an Expo Android/iOS client. The clients use the same API. The app does not seed demo accounts, posts, messages, profiles, or activity. New members see honest empty states. Both clients show follower/following counts before opening their member lists and provide an Activities screen with unread counts and read controls.

## Run the API and web app (Windows)

From `C:\Users\sylde\OneDrive\Desktop\ZORLII_app` (the folder containing this `zorlii_app` package):

```powershell
py -m venv .\.venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r .\zorlii_app\requirements.txt
py -m uvicorn zorlii_app.main:app --host 0.0.0.0 --port 8000
```

Open the web client at `http://127.0.0.1:8000/` and interactive API docs at `http://127.0.0.1:8000/docs`. `0.0.0.0` is used so a phone on the same network can reach the API; do not expose this development server directly to the public internet.

The default SQLite file is `zorlii_app\data\zorlii.sqlite3`. Set `ZORLII_DB_PATH` to use another file. Profile photos are normalized to JPEG and stored in an `avatars` directory beside the configured database. Post photos, animated GIFs, and MP4, MOV, or WebM videos are stored in a `media` directory beside it. Keep the database, avatar directory, and media directory on persistent storage; for Railway, mount the volume at `/data` and set `ZORLII_DB_PATH=/data/zorlii.sqlite3` so these files are stored under `/data`. There is no per-user media quota; Railway volume capacity remains finite and should be monitored. Uploads are technically capped at 50 MB per file, with up to four media items on one post, to protect app availability; this implementation detail is not shown in the upload UI. No external storage credentials are needed. Startup migrations are additive (`CREATE TABLE IF NOT EXISTS`, plus the existing username column/backfill, profile-photo column, and post-media table); they do not drop tables, delete profiles, or reset user content. Back up the DB and all three storage directories before deployment or upgrades.

## Email verification and password recovery

Registration and password recovery send a six-digit OTP by SMTP. No account is created until signup OTP verification succeeds. Recovery requires the OTP together with the email and new password. Codes expire in 10 minutes, allow five attempts, and are protected by a resend cooldown plus per-email/per-IP hourly request limits. Unknown recovery addresses receive the same API response as known addresses; no OTP or reset token appears in API responses or logs.

New signup and password-reset passwords must be 4–128 characters and include an uppercase letter, a lowercase letter, a number, and a special character. The API enforces the rule regardless of client; the web and Expo forms show the same guidance. Existing accounts and their stored password hashes are preserved, and sign-in continues to accept existing passwords.

SMTP credentials and the OTP HMAC key are **not included**. Configure them in a private local `.env` file:

```powershell
Copy-Item .\zorlii_app\.env.example .\zorlii_app\.env
notepad .\zorlii_app\.env
```

Generate a private OTP key locally and save it directly in `.env`:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set that value as `ZORLII_OTP_SECRET`. For Railway Free, Trial, or Hobby plans, use Resend's HTTPS API: set `ZORLII_EMAIL_PROVIDER=resend`, add `ZORLII_RESEND_API_KEY`, and set `ZORLII_EMAIL_FROM` to a sender on a domain verified in Resend. Add the Resend-provided DNS records to your DNS provider; do not proxy its CNAME records through Cloudflare. A sending subdomain such as `auth.example.com` is recommended. Keep API keys in Railway Variables and `.env` private; never paste credentials into chat or commit them. SMTP remains available on platforms/plans that permit outbound SMTP; use `ZORLII_EMAIL_PROVIDER=smtp` and configure the SMTP variables below. For Gmail/Google Workspace, enable 2-Step Verification, create a Google App Password, and use it in `ZORLII_SMTP_PASSWORD`—not your normal Google password. The app removes Gmail App Password spacing. Retain the same OTP secret across restarts; rotating it invalidates pending codes. The database stores only keyed OTP digests and scrypt-hashed pending signup passwords. `/api/health` reports whether email settings are present; it does not test the provider API key or guarantee inbox delivery.

## Expo mobile client

The Expo source is in `zorlii_app\mobile`. It stores bearer sessions with Expo SecureStore and supports email-verified sign-up, OTP password recovery, sign-in, Pulse, posts and replies with photos/videos, likes, reposts, quotes, bookmarks, search, follow, follower/following lists, Activities, private conversations, profile-photo selection/change/removal, profile/consent settings, content and account reports, blocking/unblocking, moderator report review, and local extractive assistance. Foreground views refresh automatically; phone push delivery uses Expo Push Service.

Conversation history is returned newest-page-first, with messages ordered chronologically within each page. The messages endpoint accepts `before_id` for older pages and returns `has_more` and `conversation_created_at`; access remains restricted to conversation participants.
Mentions in posts and replies create an Activity and schedule a push for each tagged account that can view the content; blocked accounts and private or otherwise inaccessible content do not receive mention alerts.
The signed-in profile exposes activity totals for posts, attachments, replies, likes, echoes, saved posts and sent messages. Profile posts use `before_id` pagination and continue to respect the viewer's access to each post.

The mini games include Tile Quest, Summit Steps, Quick Math, Word Scramble, Odd One Out, Number Pattern and Color Match. In Summit Steps, each climb requires a reachable hold within 12 seconds. Each game keeps one all-time best score per member; the leaderboard shows usernames, display names and scores to signed-in members, except across blocks. Games require an internet connection. Moves and scores are calculated on the server rather than accepted from clients; this does not prevent automated play. Game data is included in account deletion and export.

Use Node.js 22.13 or newer for the current Expo SDK. An Android APK can be built locally with the Android SDK installed, or through EAS Build. The project includes `eas.json` profiles for an internal-test APK and a production Android App Bundle.

1. Start the backend as above. Find the computer's private Wi-Fi IPv4 address (for example with `ipconfig`).
2. Ensure the phone and computer are on the same Wi-Fi and allow inbound TCP port 8000 on the Windows **private-network** firewall profile.
3. In a second PowerShell window:

```powershell
cd C:\Users\sylde\OneDrive\Desktop\ZORLII_app\zorlii_app\mobile
$env:EXPO_PUBLIC_API_URL = "http://192.168.1.156:8000" # replace with this PC's current Wi-Fi IPv4
$env:APP_ENV = "development"
npm install
npm run typecheck
npx expo start
```

Scan the Expo Go QR code on Android or iOS. Android emulator users can use `http://10.0.2.2:8000`; a physical Android device needs the computer's LAN IP. On a physical iPhone, use the same LAN URL. iOS simulator/device builds require the Apple toolchain/account; this project has not built or published release binaries. Use HTTPS rather than plain HTTP outside local development.

### Build and install a local Android test APK

The local test APK uses HTTP to reach the development server over your private Wi-Fi. The Android app permits cleartext only because this preview profile targets a local development API; use HTTPS and disable cleartext before any public release.

```powershell
cd C:\Users\sylde\OneDrive\Desktop\ZORLII_app\zorlii_app\mobile
$env:EXPO_PUBLIC_API_URL = "http://192.168.1.156:8000" # replace with this PC's current Wi-Fi IPv4
$env:APP_ENV = "development"
npx expo prebuild --platform android
.\android\gradlew.bat assembleDebug
```

The APK is created at `mobile\android\app\build\outputs\apk\debug\app-debug.apk`. Copy it to the Android phone and open it to install (allow installs from that source if Android prompts). Keep the FastAPI server running and the phone on the same Wi-Fi. The IP address is compiled into the APK, so rebuild if it changes. This is a debug/test APK, not a Play Store release.

For an EAS cloud preview APK instead, sign in with an Expo account and run `npx eas-cli@latest build --platform android --profile preview`; the profile uses `https://zorlii.app`. Production builds use the same HTTPS API, disable cleartext traffic, and produce an Android App Bundle:

```powershell
npx eas-cli@latest build --platform android --profile production
```

EAS requires Expo authentication and Android signing credentials; it can generate and securely manage the Android keystore. The Expo config contains the Zorlii project's owner and project ID.

## API overview

- `POST /api/auth/register`, `/register/resend`, `/register/verify`, `/login`, `/logout`, `/forgot-password`, `/reset-password`; `/api/me`
- Registration accepts `email`, `password`, and `accept_terms: true`; `username` and `display_name` remain optional for existing clients. Verification returns the generated username and display name when omitted. `PATCH /api/profile` accepts a username of 3–24 ASCII letters, numbers or underscores, normalized to lowercase; unavailable or reserved names return 409. Renaming retains account data, sessions and relationships; old text mentions are not rewritten.
- Historical usernames that already differ only by case are preserved rather than silently renamed. Until those members choose distinct names, case-insensitive username lookups resolve to the lowest user ID; new registrations and changes cannot introduce another collision.
- `GET/PATCH /api/profile`; `PUT/DELETE /api/profile/avatar`; `GET /api/avatars/{user_id}`; `GET /api/users/{username}`, `/posts`, `/followers`, and `/following`; `POST /api/users/{username}/follow`
- `GET /api/hashtags/{tag}` returns posts with the exact hashtag, ignoring case and respecting post visibility and blocks. Use `before_id` to load older results. Hashtags contain letters, numbers, or underscores (up to 100 characters).
- `GET /api/games` lists games; `POST /api/games/{game}/start` starts a run; `GET /api/games/{game}/run` retrieves the current run; `POST /api/games/{game}/move` advances it with its `run_id`, `revision`, and action. `GET /api/games/{game}/leaderboard` returns ranked personal bests with `limit` and `offset`. Runs end after 1,000 moves at most.
- The five multiple-choice game IDs are `quick-math`, `word-scramble`, `odd-one-out`, `number-pattern`, and `color-match`. Their state contains `prompt`, `choices` (objects with string `id` and `label`), `round`, `total_rounds` (10), `score`, and `over`; after a move it also contains `correct` for the previous answer. Submit the selected choice's `id` as `action`. Each correct answer earns 10 points; wrong answers earn zero. The server stores answers privately, checks revisions and maintains the best score as the run progresses. At completion `prompt` is empty and `choices` is empty.
- `PATCH /api/settings/theme` stores the signed-in member's accent colour as a six-digit hex value in `theme_color`, so it is available through the profile across devices. The startup migration adds this preference without replacing existing account data.
- `GET /api/blocks`; `POST /api/users/{username}/block` toggles a block; `POST /api/reports` submits a post or account report. Moderator-only report review and reported-post removal use `/api/moderation/*`.
- `GET /api/feed?scope=all|following|bookmarks` returns posts newest first by creation time, even when older posts are reposted. `POST /api/posts` supports quotes; `/api/posts/media` supports quoted posts with uploaded media. Authors can edit text with `PATCH /api/posts/{id}` or `PATCH /api/replies/{id}` and delete their own content; editing retains existing media and quotes. New, visible mentions in edited text generate activity. Post reposts, reply reactions/reposts, and reply media use the `/api/posts/*` and `/api/replies/*` routes.
- `GET /api/posts/{id}` returns replies in ascending ID order. Use `limit` (1–100) and the response's `next_after_id` as `after_id` to fetch subsequent pages while `has_more` is true; blocked accounts remain filtered on every page.
- `GET/POST /api/conversations`; participant-only message read/send/edit/delete
- `GET /api/search?q=...` searches display names and usernames (prefix a username with `@`); `GET /api/notifications` supplies Activities; `PATCH /api/notifications/{id}/read` and `POST /api/notifications/read` update read state; `GET /api/recommendations`
- `POST/DELETE /api/push-token` registers or removes the signed-in device's Expo push token.
- `GET /api/account/export` downloads the authenticated member's account data; `DELETE /api/account` permanently deletes the account after password confirmation.
- `POST /api/context` is local extractive selection only, gated by saved opt-in and per-request consent.

Web authentication uses HttpOnly SameSite cookies. Mobile authentication uses bearer tokens; session tokens are stored hashed server-side and expiry/logout/password reset revoke sessions. Private and followers-only posts are filtered on the server, and private messages require conversation membership. Likes, follows, replies, quotes, reposts, and messages produce persisted activity records; clients can list events, see unread counts, and mark items or all items as read. The opt-in recommendation endpoint compares a member's profile to **actual public posts only**, with no bundled corpus. Context assistance handles only text supplied for that request and does not persist it or call an external service.

Members can export their profile and account-owned social data as JSON. Exports never contain password hashes or session tokens. Account deletion requires the current password (and an additional username confirmation in the clients); it removes the account, profile, posts, replies, follows, reactions, bookmarks, notifications, and messages sent by that member. Messages written by other participants remain available to them.

## Play Store policy and moderation setup

The public policy pages are served at `https://zorlii.app/privacy`, `https://zorlii.app/terms`, and `https://zorlii.app/account-deletion`. New members confirm that they are at least 18 and accept the Terms of Use and Privacy Policy during signup. Existing members are prompted to accept before contributing content. Users can report posts or accounts, block and unblock accounts, and moderators can review reports and remove reported posts in the app.

Push registration needs a linked EAS project ID in the Expo config and valid Android FCM and iOS APNs credentials in EAS. The backend sends generic activity alerts via Expo Push Service after its API response; it does not include direct-message text in push previews. Until push credentials and a production build are configured, automatic foreground refresh still works, but background/closed-app pushes are not guaranteed.
Push ticket errors are logged by category, without logging device tokens. `InvalidCredentials` and `MismatchSenderId` indicate that the provider configuration needs attention; an accepted ticket alone does not confirm delivery to a device.

The Zorlii EAS project ID is configured in `mobile/app.json`; `EXPO_PUBLIC_EAS_PROJECT_ID` can override it for another project. Android FCM and iOS APNs configuration is still required, followed by a new build and an end-to-end notification test. After sign-in and terms acceptance, Android creates the activity channel and requests notification permission before checking push configuration. Use **Enable activity alerts** in settings to retry; if the system no longer permits another prompt, choose **Open settings** to allow notifications and then retry. Test push using a standalone development or production build on a physical device or an Android emulator with Google Play services; Expo Go is not a production push test environment.

For local Android builds, set `ZORLII_GOOGLE_SERVICES_FILE` to the absolute path of the Firebase Android configuration file. This machine's copy is outside the synced source directory:

```powershell
$env:ZORLII_GOOGLE_SERVICES_FILE = Join-Path $env:LOCALAPPDATA 'Zorlii\firebase\google-services.json'
```

The Android Google Services plugin reads this file during the build and fails if no configuration is available. The file is not tracked by Git. A build containing the Firebase configuration does not by itself establish server-side push delivery.

On Android, `SERVICE_NOT_AVAILABLE` while obtaining a push token can indicate that Google Play services or FCM is temporarily unreachable; check the device's connectivity and Google Play services, then retry from settings. This error alone does not identify a single cause. Separately, Expo needs an [FCM V1 service account configured](https://docs.expo.dev/push-notifications/fcm-credentials/) to deliver Android pushes. Never add its private key to the repository or share it in support messages.

Set `ZORLII_MODERATOR_EMAILS` in the server environment to a comma-separated list of verified Zorlii account email addresses that should receive moderator tools. Keep this list restricted to trusted moderators: it permits report review and removal of any post. Client-side controls do not grant access. For local Windows development, a terminal already open before the user environment was updated can load the saved setting with `$env:ZORLII_MODERATOR_EMAILS = [Environment]::GetEnvironmentVariable('ZORLII_MODERATOR_EMAILS', 'User')` before starting the API. Local settings do not grant privileges on the live server. Configure the support contact shown on the public policy pages by updating `benefit19990@gmail.com` in `legal/privacy.html`, `legal/terms.html`, and `legal/account-deletion.html` if the support address changes.

The Android application ID is `com.zorlii.app`; it is configured for a production Android App Bundle and Expo SDK 58's default target SDK is API 36. Confirm that the Play Console app listing uses this exact ID before its first upload. The production EAS profile requires an Expo account and project link. A Play Console personal developer account created after November 13, 2023 must complete the Play Console closed-test requirement (at least 12 testers opted in continuously for 14 days) before requesting production access. Store listing assets, the Data safety form, content rating, app-access instructions, and the closed test still need to be completed in Play Console; this repository does not submit or publish the app.

## Tests and checks

From `C:\Users\sylde\OneDrive\Desktop\ZORLII_app`:

```powershell
py -m unittest discover -s .\zorlii_app\tests -v
py -m compileall .\zorlii_app
cd .\zorlii_app\mobile
npm run typecheck
```

API tests inject in-memory mail senders; they do not contact SMTP or expose codes in responses. Avatar tests exercise format validation, size limits, persistence, ownership, replacement, removal, and deletion cleanup. UI tests cover OTP recovery, profile-photo controls, real-data empty states, and local-assistance consent affordances.

## MVP boundaries

This is a local-development MVP, not a complete production deployment recipe: HTTPS termination, CSRF strategy for cookie clients, stronger production abuse controls, database migration tooling, backups, and production observability still need deployment planning. User reporting, blocking, terms acceptance, public policy pages, and moderator report actions are implemented, but moderators must be configured and reports must be actively reviewed. Email OTP verification works when the email provider and private OTP key are configured; live provider delivery has not been re-verified here. The app has not been submitted to or published in an app store.

The current Expo 58 dependency audit reports five **moderate** transitive advisories in Expo CLI's `glob`/`minimatch` tooling (no high or critical findings); the audit's offered fix is a major Expo SDK downgrade. Review this dependency tree again before a release and update Expo when a compatible patch is available.
