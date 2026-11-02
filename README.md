# Relay — WhatsApp Chain V0.2

**What the user does:** Open an HTTPS link from WhatsApp → watch the current merged clip → record **3 seconds** → after video uploads and processes, watch the **automatically merged video** → tap **Send to next friend on WhatsApp**. Every recipient gets the accumulated video and can add their own clip. **Nobody has to edit or install an app.**

## Important distinction

This is an **implemented, locally tested, temporary private pilot**, not a live public URL. The site needs a hosted HTTPS origin and a persistent disk to work on separate real phones. A Share button opens WhatsApp for the user to choose a friend and press Send. Personal WhatsApp cannot automatically run FFmpeg or message friends, and there is no WhatsApp bot/integration. WhatsApp URL previews show a thumbnail, not necessarily the video inline. Another button uses Android's share sheet to share the actual MP4; sharing a file with a separate invitation link may require two taps depending on WhatsApp's behavior.

## Local run

Requirements: Python 3.11+, `ffmpeg`/`ffprobe` on PATH.

```bash
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8792
```

Open http://localhost:8792. Desktop file upload works, but live camera access from a **different phone requires HTTPS**. The UI includes a native phone camera fallback for mobile in-app browser restrictions.

## Pilot hosting (not deployed)

Build Dockerfile on any HTTPS container host with a **persistent volume**, env vars `RELAY_DATA_DIR=/data` and `RELAY_PUBLIC_URL=https://your-hostname.example`, a 10+ GB volume mounted to `/data`, a private random `RELAY_PILOT_CODE` for new chains, and one worker. Deleting/restarting a host **without persistent storage destroys videos**. Disk and abuse-limits must be enforced at the proxy. This is not suitable for open public traffic.

## Behavior and limits

- 1–8 people per chain; 3.25 s max per segment, 360×640, 24fps, MP4 H.264/AAC. The segment is encoded once; subsequent stitches concatenate pre-normalized clips. The time to deliver is **upload time + encoding time + network latency**, not literally zero. This design can achieve fast turnaround on a reasonably sized server, subject to device/connection performance.
- Original uploads are deleted after processing. Clips, finished videos, and tokens expire automatically after 48 hours when cleanup runs. Starter has a delete URL stored in their browser; retain it if needed.
- Links are unlisted secret tokens, not person-specific authorization. Anybody possessing a link can view the recordings. Anyone with a current join link can submit a clip. If two people race, the first accepted upload wins; one chain has **one current next slot**.
- No name/phone/email/contacts are collected. No app install, no accounts, no AI generation, no video editing.
- The v0 trick uses a **hard cut** between video segments. For a smoother transition, both people cover/uncover the camera with a hand around the cut. It is not cinematic portal compositing.

## Required gates before any open launch

Restrict to consenting adults in a trusted group. Do not put private footage in a publicly indexed web service. Provide HTTPS, durable storage, upload/request/IP quotas, moderation/takedown, safe media transcoding isolation, browser QA on physical Android and iOS, abuse reporting, consent and retention policies, and media malware isolation. Currently FFmpeg processes uploaded files in the web container: production should isolate untrusted input. This build has **no public moderation / spam controls** and is intentionally NOT live.

## Endpoints

- `POST /api/new` form with video: creates chain and first video.
- `GET /watch/<view>` auto-assembled MP4 with one-tap WhatsApp forward CTA.
- `GET /join/<invite>` watch current video, record next clip.
- `POST /api/join/<invite>` form with video: atomically claims the next slot and assembles new MP4.
- `GET /video/<view>.mp4`: completed video for that step.
- `GET/POST /delete/<owner>` / `/api/delete/<owner>`: delete chain (POST only actual deletion).

## Test

`python -m pytest tests -q` (needs pytest, httpx). Tests use synthetic clips and do not establish end-to-end real-phone QA.


## Render FREE staging limitations (November 2026)

This code can run on the free Render web plan for a **short, supervised two-phone test**, not a reliable distributed chain. Render spins down free services after approximately 15 minutes idle and destroys ephemeral file changes on spin-down, deploy or restart. **All chain videos and SQLite records will disappear on spin-down.** The intended 48-hour retention is only a maximum, not a promise on the free host. HTTPS and secret tokens do not make this suitable for sensitive recordings. For a real friends pilot, use paid persistent disk or a managed private object store with explicit cost approval, media abuse controls and isolation. Do not upload personal/sensitive footage to the free demo.

Environment: `RELAY_REQUIRE_PILOT_CODE=1`, nonempty `RELAY_PILOT_CODE`, `RELAY_MAX_ACTIVE_CHAINS=6`, `RELAY_LIFETIME_HOURS=2`, `RELAY_DATA_DIR=/app/.data`. No persistent storage is attached. One app worker.
