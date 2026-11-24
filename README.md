# JARVIS ? Local Desktop AI Assistant

A free-first, local-first Windows desktop assistant powered by LM Studio and local Gemma models.

## Features
- Animated JARVIS voice interface with browser microphone input and ElevenLabs-compatible speech output (browser speech fallback)
- Browser wake phrase listener and conversational voice mode; core backend can enumerate installed Windows speech voices and recognition languages and perform bounded dictation in a selected installed culture
- Local chat through the LM Studio OpenAI-compatible API
- SQLite personal memory and local reminders
- Switching between installed Gemma 4 models
- Allowlisted quick actions for Notepad, Calculator, File Explorer and browser
- PC Control workspace: live desktop screenshot, local Gemma 4 visual understanding, UI Automation inspection, coordinate-based mouse clicks, double/right clicks, scrolling, keyboard typing and an approved shortcut set
- AI Computer Operator: screenshot-grounded multi-step plans with autonomous execution for routine actions; destructive, financial, external-send and security-sensitive actions remain protected
- File Explorer workspace: browse folders, open files, rename items and send items to the Windows Recycle Bin
- Windows status view with active-window information and running-process inventory
- Server binds to 127.0.0.1 only

## Requirements
- Windows 10/11
- Python 3.10+ (tested with Python 3.15)
- LM Studio with a Gemma 4 chat model loaded and its local server enabled on port 1234
- Microsoft Edge or Google Chrome; microphone permission enabled for browser voice input
- Windows speech recognition language pack compatible with the listener

Install Python dependencies from the project folder:

    python -m pip install -r requirements.txt

## Run
1. Open LM Studio and start its local server on port 1234.
2. Load a Gemma 4 model.
3. Run start-jarvis.bat.
4. JARVIS opens at http://127.0.0.1:8765.
5. Open PC CONTROL in the top bar to view the desktop and use mouse/keyboard controls.

## PC Control
- Click PC CONTROL to open the control workspace.
- Refresh Screen captures the current Windows desktop. Click a location in the preview to click the same location on the PC.
- Use the keyboard field to type into the currently focused application.
- Shortcut buttons are intentionally allowlisted; dangerous system shortcuts and arbitrary shell execution are not exposed.
- Ask JARVIS to perform a task in the AI Computer Operator panel. It uses a local screenshot and local Gemma 4 model to prepare up to 12 actions, then executes routine actions automatically. Destructive, financial, external-send and security-sensitive actions remain protected. Voice commands can start a plan with ?plan computer task: ??.
- Browse a folder by entering its path. Open files/folders, rename items, or send files to the Recycle Bin. Trash operations require confirmation.
- PyAutoGUI's fail-safe remains enabled: moving the mouse to the top-left corner can abort a stuck automation.

Computer control is powerful and can affect the active Windows session. Review the screenshot and target application before acting. JARVIS does not bypass UAC, Windows security, password prompts or application permissions. It should request confirmation for consequential or irreversible operations. Visual model plans are estimates: review every step and verify the result before continuing.

## Wake phrases
The background PowerShell listener recognizes: Open Jarvis, Hey Jarvis, Okay Jarvis, OK Jarvis, Wake up Jarvis, Wake up, and Jarvis. Recognition depends on the active microphone, Windows speech-recognition language and room conditions.

## Persistent memory
Saved notes and reminders are stored in jarvis_memory.sqlite3 beside app.py. The database is intentionally excluded from Git.

## Security and privacy
The HTTP server binds to 127.0.0.1, validates local Host/Origin headers and JSON write requests, and is intended for local use only. Do not expose it to a LAN, reverse proxy or public internet without authentication, CSRF protection, authorization, rate limiting and a hardened deployment design. API keys are read from Windows user environment variables and must never be committed. PC Control sends screenshots and input actions only to the local JARVIS server.

## License
MIT ? see LICENSE.
## Next-generation JARVIS architecture

The modular backend is being built alongside the existing Windows app to preserve working desktop and mobile functionality.

- Architecture: `docs/architecture/SYSTEM-ARCHITECTURE.md`
- Phase tracker: `docs/architecture/PHASE-PLAN.md`
- New backend: `backend/`
- Backend setup and commands: `backend/README.md`

The new FastAPI service currently runs separately at `http://127.0.0.1:8766`; the legacy dashboard/service remains on its existing port. Development currently uses Python 3.13 because this PC has Python 3.13 and 3.15 installed, but not 3.12. The new backend declares Python 3.12+ compatibility.

**Security status:** the new API is loopback-only. Memory content is encrypted at rest with Windows DPAPI, and the agent kill switch and approval gates are enforced. Credentials and other SQLite metadata are not yet encrypted, and authenticated remote access, rate limits and sandbox hardening remain incomplete. Do not expose the new service remotely.

## Security review workflow

- Claude-BugHunter is maintained separately at `E:\AI-TOOLS\Claude-BugHunter`.
- Its Agent Skills are installed for Codex in the user-level `.agents\skills` directory.
- This repository includes `.agents/skills/jarvis-security-review/SKILL.md` for defensive, local-only reviews of JARVIS using the BugHunter knowledge bundle.
- Integration notes and the current boundary are documented in `docs/security/BUGHUNTER-INTEGRATION.md`.
- This is a development-time Codex integration, not a live JARVIS runtime scanner. The running assistant does not automatically execute BugHunter skills.
