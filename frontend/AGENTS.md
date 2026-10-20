# Frontend task routing

- For frontend work, read [`docs/ui-system.md`](../docs/ui-system.md) and the relevant page Spec first. `docs/ui-system.md` is the final visual and interaction authority; surface conflicts from a Skill explicitly before proceeding. Preserve business behavior, API contracts, routes, and user flows unless the task changes them.
- Route only the relevant Skill for a task; do not load every design Skill:
  - `.agents/skills/frontend-design` — general frontend design and implementation; use as the default design lead for ordinary UI work.
  - `.agents/skills/ui-ux-pro-max` — new page direction, layout, typography, and component options. Treat search results as references and reconcile them with the existing product and UI system.
  - `.agents/skills/impeccable` — existing-page refinement, layout/type critique, and visual quality review. Keep its edit hooks off unless explicitly requested.
  - `.agents/skills/emil-design-eng` — motion design or complex interaction details; use `find-animation-opportunities` / `review-animations` for motion audits and `animate` for requested implementation. Do not load for ordinary static UI changes.
  - `.agents/skills/react-best-practices` — only when changing React rendering, data flow, fetching, or performance; omit for CSS-only and backend-only work.
- Choose the matching Dashboard, List, or Detail Reference before editing. Reuse existing components and CSS; add no dependency or animation library for ordinary interaction feedback.
- For visual work, use the smallest matching Skill set, inspect the rendered result in a real browser when available, and follow the repository's Spec Review, Implementation, and Final Gate process for the task's risk.
