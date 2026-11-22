# JARVIS — Local Desktop AI Assistant

A free-first, local-first Windows voice assistant prototype powered by LM Studio and Gemma. No cloud API key is required.

## Features
- Dark gold-accented assistant dashboard with animated orb
- Browser speech-to-text (Chrome/Edge), continuous "Hey Jarvis" wake phrase while the page is open, and spoken replies
- Local chat through the LM Studio OpenAI-compatible API
- SQLite persistent personal memory, saved locally on the PC and included in relevant chat context
- Add and delete saved memories from the dashboard
- Live LM Studio status and in-dashboard switching between available Gemma 4 models
- Safe, allowlisted quick actions: Notepad, Calculator, File Explorer, browser
- Server binds to 127.0.0.1 only; no arbitrary shell command endpoint

## Requirements
- Windows 10/11
- Python 3.10+
- LM Studio with a Gemma 4 chat model loaded and its local server running on port 1234
- Chrome or Microsoft Edge; allow microphone access for voice features

## Run
1. Open LM Studio and start its local server on port 1234.
2. Load a Gemma 4 model.
3. Run start-jarvis.bat in this folder.
4. Open http://127.0.0.1:8765
5. To use voice, allow microphone access and click ENABLE WAKE WORD. Say "Hey Jarvis" while the page remains open and active.

## Persistent memory
Use the Personal Memory box to save notes. They are stored in jarvis_memory.sqlite3 beside app.py and are automatically added to the model's context. Delete notes from the dashboard when no longer needed. The database is intentionally excluded from Git.

## Configuration
Environment overrides: LM_STUDIO_URL, JARVIS_MODEL, JARVIS_PORT.

## Security and privacy
The server binds only to 127.0.0.1. It is not exposed to your LAN or internet. PC actions are restricted to fixed allowlisted programs and a fixed browser URL. Saved memories remain on the local machine and should never be committed or uploaded. Do not expose this server publicly without authentication, CSRF protections, rate limiting, and a hardened deployment design.

## Current status
Working local prototype. Python syntax, HTTP dashboard, local LM Studio connection, persistent memory save/recall/delete, and blocked unapproved actions have been tested. Browser wake phrase depends on browser microphone permissions and the page staying open. Full desktop automation, native always-on wake word, advanced permissions, installer packaging, and cross-platform support are future work.

## License
MIT — see LICENSE.
