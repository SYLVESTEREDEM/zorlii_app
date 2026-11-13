# Zorlii

Zorlii is a persistent, small-community social MVP: FastAPI + SQLite API, a branded web client, and an Expo Android/iOS client. The clients use the same API. The app does not seed demo accounts, posts, messages, profiles, or activity. New members see honest empty states. Both clients support follower/following lists and readable notifications with unread counts and read controls.

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

The Expo source is in `zorlii_app\mobile`. It stores bearer sessions with Expo SecureStore and supports email-verified sign-up, OTP password recovery, sign-in, Pulse, posting, reactions, bookmarks, replies, search, follow, follower/following lists, notifications, private conversations, profile-photo selection/change/removal, profile/consent settings, and local extractive assistance.

Use Node.js 22.13 or newer for the current Expo SDK. An Android APK can be built locally with the Android SDK installed, or through EAS Build. The project includes `eas.json` profiles for an internal-test APK and a production Android App Bundle.

1. Start the backend as above. Find the computer's private Wi-Fi IPv4 address (for example with `ipconfig`).
2. Ensure the phone and computer are on the same Wi-Fi and allow inbound TCP port 8000 on the Windows **private-network** firewall profile.
3. In a second PowerShell window:

```powershell
cd C:\Users\sylde\OneDrive\Desktop\ZORLII_app\zorlii_app\mobile
$env:EXPO_PUBLIC_API_URL = "http://192.168.1.156:8000" # replace with this PC's current Wi-Fi IPv4
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
npx expo prebuild --platform android
.\android\gradlew.bat assembleDebug
```

The APK is created at `mobile\android\app\build\outputs\apk\debug\app-debug.apk`. Copy it to the Android phone and open it to install (allow installs from that source if Android prompts). Keep the FastAPI server running and the phone on the same Wi-Fi. The IP address is compiled into the APK, so rebuild if it changes. This is a debug/test APK, not a Play Store release.

For an EAS cloud preview APK instead, sign in with an Expo account, set `EXPO_PUBLIC_API_URL` to a reachable HTTPS API URL, then run `npx eas-cli@latest build --platform android --profile preview`. EAS requires Expo authentication. Production store builds also require signing and release configuration.

## API overview

- `POST /api/auth/register`, `/register/resend`, `/register/verify`, `/login`, `/logout`, `/forgot-password`, `/reset-password`; `/api/me`
- `GET/PATCH /api/profile`; `PUT/DELETE /api/profile/avatar`; `GET /api/avatars/{user_id}`; `GET /api/users/{username}`, `/posts`, `/followers`, and `/following`; `POST /api/users/{username}/follow`
- `GET /api/feed?scope=all|following|bookmarks`; `POST /api/posts`; post read/delete and reply/reaction/bookmark actions
- `GET/POST /api/conversations`; participant-only message read/send/edit/delete
- `GET /api/search?q=...`; `GET /api/notifications`, `PATCH /api/notifications/{id}/read`, and `POST /api/notifications/read`; `GET /api/recommendations`
- `GET /api/account/export` downloads the authenticated member's account data; `DELETE /api/account` permanently deletes the account after password confirmation.
- `POST /api/context` is local extractive selection only, gated by saved opt-in and per-request consent.

Web authentication uses HttpOnly SameSite cookies. Mobile authentication uses bearer tokens; session tokens are stored hashed server-side and expiry/logout/password reset revoke sessions. Private and followers-only posts are filtered on the server, and private messages require conversation membership. Likes, follows, replies, and reactions produce persisted notifications; both clients can list these events, see unread counts, and mark items or all items as read. Follower/following endpoints return real member profiles with pagination. The opt-in recommendation endpoint compares a member's profile to **actual public posts only**, with no bundled corpus. Context assistance handles only text supplied for that request and does not persist it or call an external service.

Members can export their profile and account-owned social data as JSON. Exports never contain password hashes or session tokens. Account deletion requires the current password (and an additional username confirmation in the clients); it removes the account, profile, posts, replies, follows, reactions, bookmarks, notifications, and messages sent by that member. Messages written by other participants remain available to them.

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

This is a local-development MVP, not a production deployment recipe: HTTPS termination, CSRF strategy for cookie clients, stronger production abuse controls, database migration tooling, backups, moderation/reporting, and production observability still need deployment planning. Email OTP verification works when SMTP and the private OTP key are configured; live provider delivery has not been verified. The UI only displays real persisted records and does not claim release-store availability.

The current Expo 58 dependency audit reports five **moderate** transitive advisories in Expo CLI's `glob`/`minimatch` tooling (no high or critical findings); the audit's offered fix is a major Expo SDK downgrade. Review this dependency tree again before a release and update Expo when a compatible patch is available.
