# Claude-BugHunter integration

## Current status

Claude-BugHunter is kept as an independent repository at `E:\AI-TOOLS\Claude-BugHunter`.

- Git remote: `https://github.com/elementalsouls/Claude-BugHunter.git`
- Installed revision at integration time: `6b710c2`
- Source bundle: 84 Agent Skills and 15 Claude Code slash commands
- Codex skill destination: `%USERPROFILE%\.agents\skills\`
- Claude Code skill destination: `%USERPROFILE%\.claude\skills\`
- JARVIS project workflow skill: `.agents/skills/jarvis-security-review/SKILL.md`

The official Windows installer was run with `-Agents -NoProfile`. It installed the Agent Skills for Codex/OpenCode and Claude Code, wrote its uninstall manifest, and did not modify the current PowerShell profile. Existing global skills were preserved; there were no same-name conflicts. The repository's own lint reported 0 errors and 11 advisory body-length warnings across 84 skills.

## Integration boundary

The integration has two distinct layers. Codex and Claude Code can use the 84 Agent Skills as development-time methodology. Separately, the JARVIS application runtime now has a native, allowlisted bridge to the installed BugHunter CLI and skill library. The runtime does not dynamically load or execute arbitrary Agent Skill Markdown as code; every executable operation is implemented in trusted JARVIS backend handlers and registered in `backend/config/skills.json`.

## Safety and maintenance

- Keep BugHunter's Git history and updates independent from JARVIS.
- Pin reviewed commits before updates; inspect upstream changes and rerun `python scripts/lint_skills.py` before reinstalling.
- Do not enable Burp/HackerOne MCP integrations without a separate need and explicit setup.
- Keep tests limited to JARVIS code, local test fixtures, and explicitly authorized systems.
- Do not put API keys, HackerOne tokens, cookies, or scan evidence containing secrets into Git.

## Runtime scanner now implemented

The native JARVIS scanner is available through POST /api/v1/security/scan, GET /api/v1/security/report, and GET /api/v1/security/status. The root JARVIS desktop app proxies these routes and recognizes the voice commands “Run a security scan” and “Read the security report”. Reports are stored locally in the ignored data/security-reports/latest.json file. The scanner is bounded, local-only, read-only for source files, redacts credential values, and writes only its report. See RUNTIME-SECURITY-SCANNER.md.

## BugHunter runtime skills

JARVIS exposes seven fixed backend skills: `bughunter.capabilities`, `bughunter.read_skill`, `bughunter.classify_url`, `bughunter.local_audit`, `bughunter.surface_local`, `bughunter.triage_finding`, and `bughunter.draft_report`. They are registered in the declarative manifest and dispatched through trusted Python handlers. Skill reads and URL classification are local operations; URL classification does not send a request to the supplied host.

The local audit runs the bounded static scanner over the JARVIS project, classifies three local API route patterns, and writes a local route-inventory manifest plus JSON/log reports under `data/bughunter`. It makes no network requests and does not run exploit tests. Triage accepts only an existing Markdown filename within `data/bughunter/findings`. Report drafting writes a new file only within `data/bughunter/reports`, refuses overwrite, and requires JARVIS approval. Active BugHunter hunting and external recon are not exposed as autonomous runtime actions.

## Future extensions

The current scanner is a lightweight static check, not a dependency audit or penetration test. Future work may add reviewed dependency checks and richer SAST rules. External reconnaissance, Burp/HackerOne integrations, and automatic remediation remain out of scope unless separately requested and explicitly approved. Any source-code remediation must be a distinct approval-gated operation.
