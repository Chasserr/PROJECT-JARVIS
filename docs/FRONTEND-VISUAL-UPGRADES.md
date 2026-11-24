# JARVIS Frontend Visual Upgrades

## MingCute Icons
- Source: `@mingcute/svg` version 3.1.0 (official `mingcute-design/mingcute-icons` package)
- License: Apache-2.0; see `web/icons/MINGCUTE-LICENSE`
- Only the icon SVGs used by the current JARVIS UI and near-term controls are copied into `web/icons/core-regular/`.
- Assets are served locally; the running dashboard does not depend on an icon CDN or a new JavaScript framework.

## Motion
- The existing particle orb and interface remain in place.
- Added lightweight CSS-only orbital rings using transform/opacity animation; no new runtime dependency.
- `prefers-reduced-motion` disables the added continuous effects.
- Keep animation work on compositor-friendly transforms and opacity; avoid layout animation and pause nonessential effects when the page is hidden.

## Agent skills
- Installed the official GSAP `gsap-core`, `gsap-performance`, and `gsap-timeline` Agent Skills from `greensock/gsap-skills` into both `.agents/skills/` (Codex) and `.claude/skills/` (Claude Code).
- These are guidance for future coding-agent work; GSAP itself is not added to the running dashboard because the current visual enhancement does not need a new runtime dependency.
- Upstream repository license is included in each agent skill directory as `GSAP-LICENSE` at the respective skills root.

## ReactBits decision
ReactBits components target React. The current JARVIS dashboard is served as vanilla HTML/CSS/JavaScript by the existing Python HTTP server. A React migration solely to consume a component library would increase complexity and risk without improving the current milestone, so ReactBits remains a design reference rather than a runtime dependency.
