# JARVIS — Local Desktop AI Assistant

A free-first, local-first Windows voice assistant powered by LM Studio and local Gemma models.

## Features
- Polished dark glass desktop-style assistant UI with an animated voice orb
- Global Windows wake listener: say **“Open Jarvis”**, **“Hey Jarvis”**, **“Wake up Jarvis”**, **“Wake up”**, or **“Jarvis”**
- Browser voice conversation and spoken replies
- Local chat through the LM Studio OpenAI-compatible API
- SQLite personal memory stored on the PC and excluded from Git
- In-dashboard switching between available Gemma 4 models
- Allowlisted quick actions: Notepad, Calculator, File Explorer, and browser
- Server binds to 127.0.0.1 only

## Requirements
- Windows 10/11
- Python 3.10+
- LM Studio with a Gemma 4 chat model loaded and local server enabled on port 1234
- Microsoft Edge or Google Chrome; microphone permission enabled for browser voice input
- Windows speech recognition language pack compatible with the listener's en-US grammar

## Run
1. Open LM Studio and start its local server on port 1234.
2. Load a Gemma 4 model.
3. Run `start-jarvis.bat`.
4. The JARVIS app window opens at `http://127.0.0.1:8765`.
5. The Windows listener can be launched from the Open JARVIS shortcut or Windows startup.

## Wake phrases
The background PowerShell listener recognizes: Open Jarvis, Hey Jarvis, Okay Jarvis, OK Jarvis, Wake up Jarvis, Wake up, and Jarvis. It launches the JARVIS Edge app window. Actual recognition depends on the active microphone, Windows speech-recognition language, and room conditions.

Inside the app, browser speech recognition can listen for the same wake phrases while the app window is open. Tap the orb to speak manually.

## Persistent memory
Use Settings → Personal Memory to save notes. They are stored in `jarvis_memory.sqlite3` beside `app.py`. This database is intentionally excluded from Git.

## Security and privacy
The server binds only to 127.0.0.1. PC actions are restricted to fixed allowlisted programs. Saved memories remain on the PC and should never be committed or uploaded. Do not expose the server publicly without authentication, CSRF protections, rate limiting, and a hardened deployment design.

## License
MIT — see LICENSE.