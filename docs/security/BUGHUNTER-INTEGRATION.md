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

This is currently a **development-time integration**: Codex can use the BugHunter knowledge skills while working in the JARVIS repository. The local JARVIS project skill directs defensive reviews to the relevant BugHunter methodology and sets a local-only, read-only default.

The JARVIS application runtime (Gemma/LM Studio assistant) does **not** automatically load or execute the 84 Codex/Claude Agent Skills. Those repository skills remain advisory Markdown for development-time use, not executable runtime permissions. JARVIS now has a separate native static scanner implemented in trusted backend code and registered as the read-only security.scan_project skill. It is not a runtime wrapper around the BugHunter repository.

## Safety and maintenance

- Keep BugHunter's Git history and updates independent from JARVIS.
- Pin reviewed commits before updates; inspect upstream changes and rerun `python scripts/lint_skills.py` before reinstalling.
- Do not enable Burp/HackerOne MCP integrations without a separate need and explicit setup.
- Keep tests limited to JARVIS code, local test fixtures, and explicitly authorized systems.
- Do not put API keys, HackerOne tokens, cookies, or scan evidence containing secrets into Git.

## Runtime scanner now implemented

The native JARVIS scanner is available through POST /api/v1/security/scan, GET /api/v1/security/report, and GET /api/v1/security/status. The root JARVIS desktop app proxies these routes and recognizes the voice commands “Run a security scan” and “Read the security report”. Reports are stored locally in the ignored data/security-reports/latest.json file. The scanner is bounded, local-only, read-only for source files, redacts credential values, and writes only its report. See RUNTIME-SECURITY-SCANNER.md.

## Future extensions

The current scanner is a lightweight static check, not the full BugHunter suite, a dependency audit, or a penetration test. Future work may add reviewed dependency checks and richer SAST rules. External reconnaissance, Burp/HackerOne integrations, and automatic remediation remain out of scope unless separately requested and explicitly approved. Any source-code remediation must be a distinct approval-gated operation.
