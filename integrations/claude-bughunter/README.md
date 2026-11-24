# Claude-BugHunter bridge for JARVIS

This integration connects the locally installed Claude-BugHunter repository to JARVIS through the existing `jarvis.skills.bughunter` adapter and the normal JARVIS skill manifest / policy / agent handler path.

## Local installation

- BugHunter repository: `E:\AI-TOOLS\Claude-BugHunter`
- JARVIS adapter: `backend/src/jarvis/skills/bughunter.py`
- Skill manifest: `backend/config/skills.json`
- Runtime handlers: `backend/src/jarvis/api.py`
- Reports: `data/bughunter/`

No paid API, HackerOne credentials, Burp integration, or cloud model is required for the local workflows below.

## Available JARVIS skills

- `bughunter.capabilities` — report the installed skill and CLI inventory.
- `bughunter.classify_url` — match a supplied HTTP(S) URL to relevant BugHunter skills. Classification is local and does not probe the URL.
- `bughunter.local_audit` — bounded local audit of JARVIS localhost, including a health check, BugHunter recon/classification, and the read-only JARVIS static scanner.

## Safety boundaries

- The built-in local audit is fixed to `localhost` / `127.0.0.1`; it does not accept an arbitrary target.
- The recon command uses passive certificate-transparency lookup, local DNS resolution, and bounded HTTP GET probes. The local workflow is not a public-target scan.
- No exploit attempts, credential attacks, state-changing tests, source modifications, or active LLM hunt runner are invoked.
- URL classification only maps URL patterns to skill guidance; it does not send a request to the supplied URL.
- Active testing of a third-party system requires a separately authorized, explicitly scoped engagement and is not exposed as an autonomous JARVIS action by this adapter.

## Verification

From `backend/`, run:

```powershell
python -m pytest -q tests/test_bughunter_bridge.py tests/test_security_scanner.py tests/test_api.py::test_security_scanner_is_registered_and_status_is_available
```

Run the bounded local audit through the adapter with the JARVIS backend Python environment and `PYTHONPATH=backend/src`. The report is written to `data/bughunter/latest-local-audit.json`.
