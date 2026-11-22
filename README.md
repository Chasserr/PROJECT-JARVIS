# JARVIS — Local Desktop AI Assistant

A free-first, local-first Windows voice assistant prototype powered by LM Studio and Gemma. No cloud API key is required.

## Features
- Dark gold-accented assistant dashboard with animated orb
- Browser speech-to-text (Chrome/Edge) and spoken replies
- Local chat through the LM Studio OpenAI-compatible API
- Health check showing whether LM Studio is reachable
- Safe quick actions: Notepad, Calculator, File Explorer
- No arbitrary shell execution; server binds to localhost only

## Requirements
- Windows 10/11
- Python 3.10+
- LM Studio with a chat model loaded
- Chrome or Microsoft Edge for browser voice recognition

## Run
1. Open LM Studio and start its local server on port 1234.
2. Load a model. Default model ID: google/gemma-4-e2b.
3. Run start-jarvis.bat in this folder.
4. Open http://127.0.0.1:8765

Environment overrides: LM_STUDIO_URL, JARVIS_MODEL, JARVIS_PORT.

## Security
The server binds only to 127.0.0.1. It does not expose the assistant to your LAN or internet. The action API only permits three fixed application launches. Do not expose this server publicly without authentication, CSRF protections, rate limiting, and a hardened deployment design.

## Current status
Early working prototype, not a full Jarvis clone. Wake-word detection, broad computer automation, persistent memory, plugins, installer packaging, and cross-platform support are future work.

## License
MIT — see LICENSE.
