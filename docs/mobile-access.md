# iPhone access and the phone line

_Last updated 2026-11-27. Everything here runs on the existing JARVIS stack: the
legacy dashboard server on port 8765 (files, PC control, voice) and the FastAPI
Core Agent on port 8767 (runs, agents, tools, telephony). No second assistant and
no second backend._

## 1. The mobile interface

`web/mobile.html` (+ `mobile.css`, `mobile.js`) is an iPhone-sized surface served
by the same dashboard process that serves the desktop UI.

Open **`/mobile`** (or `/mobile.html`) in Safari on the iPhone:

- **Chat** — text commands, quick commands, the spoken-reply toggle, and the
  existing command handling (open/close applications with a YES/NO confirmation).
- **Agents** — delegate a task to JARVIS Core, then watch real runs with status,
  executed-vs-planned step progress, answers and errors. Runs that pause for
  approval show Approve/Reject; running runs show Cancel. The roster below lists
  every specialist with its probe-derived status.
- **PC** — open and close applications, type into the active window, inspect the
  active window's controls, and search local files. Every request goes to the
  existing PC-control endpoints; nothing is simulated.
- **Files** — reports JARVIS has written (`/api/reports`), each downloadable, and
  a file search across the configured roots.
- **Line** — the real telephony status from Core, including the exact missing
  environment variables.

Voice input uses the browser's speech recognition (Safari/Chrome). Spoken replies
use the local Kokoro endpoint (`/api/voice/speak`) when it is available and fall
back to the system voice. The toggle is remembered on the device.

Install it like an app: **Share → Add to Home Screen**. The manifest provides the
standalone title and status bar; there is no service worker, so the page needs
the PC to be reachable.

## 2. Remote access without exposing the PC

The dashboard already refuses anything that is not an approved local or tailnet
request:

- the server binds `127.0.0.1:8765` only;
- requests must carry `Host: 127.0.0.1:8765`, `localhost:8765`, or the Tailscale
  Serve host;
- tailnet requests must also carry the `Tailscale-User-Login` header that
  Tailscale injects for an authenticated device;
- cross-origin requests from any other origin are rejected;
- `POST`/`DELETE` additionally require a JSON content type.

That is the existing authentication layer and it is unchanged. Do **not** forward
port 8765 on the router or open it in Windows Firewall. Reach it through the
existing Tailscale Serve address (`https://riqco.taild4d092.ts.net`), which
terminates TLS and proves the device identity.

The Core Agent on 8767 keeps its own bearer token (`JARVIS_API_TOKEN`) and is
never exposed directly; the dashboard proxies to it.

## 3. The telephone line

Implemented in `backend/src/jarvis/telephony/` (see
[always-available.md](architecture/always-available.md) for the design). It is
real Twilio infrastructure, not a simulation:

- inbound: Twilio posts to `POST /telephony/voice`, which is verified with the
  provider signature **and** the caller allowlist, greets, then listens with
  speech recognition;
- each spoken turn is handed to the same Core Agent loop, so memory, tools,
  permissions, approvals and the audit log all apply;
- the call holds with a poll loop while the run finishes, then reads back the
  real outcome — including "this needs approval in the desktop console" when a
  confirmation-tier tool pauses;
- outbound: `POST /api/v1/telephony/calls` (token protected) or the
  `phone.call` tool, which is `CONFIRM` + `dangerous`.

### What you must provide

In `backend/.env`:

```
JARVIS_TELEPHONY_PROVIDER=twilio
JARVIS_TWILIO_ACCOUNT_SID=AC...
JARVIS_TWILIO_AUTH_TOKEN=...
JARVIS_TWILIO_FROM_NUMBER=+1...
JARVIS_TELEPHONY_PUBLIC_BASE_URL=https://<your-public-https-origin>
JARVIS_TELEPHONY_ALLOWED_CALLERS=+34...        # your own number(s)
```

Then in the Twilio console set the number's **voice webhook** to
`POST {JARVIS_TELEPHONY_PUBLIC_BASE_URL}/telephony/voice`.

`JARVIS_TELEPHONY_PUBLIC_BASE_URL` must be an HTTPS origin that Twilio can reach
and that forwards to this machine. A tunnel is the only new exposure this adds;
the webhook paths require a valid Twilio signature, so an unsigned request is
answered with `403`.

### Cost

- Twilio phone number: a small monthly rental.
- Inbound/outbound minutes: per-minute charges.
- Speech recognition inside `<Gather>` and `<Say>` speech: included in Twilio
  voice pricing for these features.

Everything else on this page is local and free.

## 4. What is still required

| Requirement | State |
| --- | --- |
| Open JARVIS on the iPhone | Works over Tailscale at `/mobile` |
| Speak to JARVIS in the app | Browser speech recognition → existing `/api/chat` |
| Hear spoken replies | Kokoro TTS with system-voice fallback |
| Call JARVIS on a real number | Code complete; needs the Twilio account, number and public HTTPS origin above |
| JARVIS answers with a natural voice | Twilio `<Say>` / the same agent loop; untested on a live call |
| Send PC commands remotely | Open, close, type, inspect, file search — all live |
| Specialist delegation | Same Core Agent; working and audited |
| Task completion notifications | In-app toast plus the Web Notifications API while the page is open; iOS needs the page installed and permission granted |
| Retrieve files created by JARVIS | `/api/reports` list plus download links |
