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

The JARVIS application runtime (Gemma/LM Studio assistant) does **not** automatically load Codex Agent Skills. No BugHunter scanner, external recon workflow, Burp MCP server, or HackerOne MCP server has been connected to the running JARVIS API. The repository's skills are advisory Markdown, not executable runtime permissions.

## Safety and maintenance

- Keep BugHunter's Git history and updates independent from JARVIS.
- Pin reviewed commits before updates; inspect upstream changes and rerun `python scripts/lint_skills.py` before reinstalling.
- Do not enable Burp/HackerOne MCP integrations without a separate need and explicit setup.
- Keep tests limited to JARVIS code, local test fixtures, and explicitly authorized systems.
- Do not put API keys, HackerOne tokens, cookies, or scan evidence containing secrets into Git.

## Next runtime integration stage

If a JARVIS in-app security feature is desired, implement a dedicated, reviewed, read-only audit handler in JARVIS's own trusted code. It should accept only approved project roots, avoid returning secret values, enforce file-size and timeout limits, audit each run, and never perform network probing or exploitation by default. Register it through `backend/config/skills.json` only after its handler and tests exist. Consequential remediation must remain approval-gated.
