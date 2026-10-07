# Design system

The UI uses aipotluck.org's **Alpha design system** (`web/src/lib/alpha-ds`, with the rules in
`web/src/lib/chat/design-system.md`; browse it live at `/designsystem`).

## How it's consumed

Unlike the Android port, nothing here is translated. A webview renders upstream's CSS natively, so
`tools/design/sync-alpha.py <aipotluck.org checkout>` copies:

| Upstream | Here |
|---|---|
| `alpha-ds/tokens/generated/tokens.css` (every token; colours as `light-dark(oklch…)`) | `ui/src/design/tokens.css`, verbatim |
| `alpha-ds/tokens/base.css` (`.ds-root` base layer) | `ui/src/design/base.css`, verbatim |
| `web/static/favicon.svg` | `src-tauri/icons/source.svg` → `cargo tauri icon` |
| Remix Icon paths (the mandated icon library) | `ui/src/design/icons.ts` |

The fonts (Plus Jakarta Sans and DM Mono, OFL) are bundled in `ui/src/design/fonts/`.
`ui/src/design/SOURCE.json` records the upstream commit and file hashes.

## Translating component recipes

Upstream's components are Svelte + Tailwind recipes. This app doesn't pull in Tailwind for a
handful of screens. Instead, `ui/src/app.css` re-expresses the recipes it needs (`.btn.primary`,
`.secondary`, `.destructive`, `.ghost`, `.card`, `.label`) in plain CSS over the same `--ds-*`
tokens, following `button.recipe.ts` rule for rule.

## Rules (from `chat/design-system.md`)

- **Reference tokens, never literals.** Use `var(--ds-fg-2)`, never `#ccc`. Layout dimensions
  (a max-width, a dot size) are the only literal px.
- **Accent is icon or badge scale only, never a surface fill.**
- **Bordered controls rest one surface tier up** (`--ds-surface-raised`), never transparent.
- **Destructive looks exactly like secondary**; only its icon takes `--ds-accent-2`.
- **Sharp corners by default.** `--ds-radius-field` is only for the paste box, as an input.
- **Left-aligned labels.** DM Mono uppercase for labels, CTAs and technical text; Plus Jakarta Sans
  for copy.
- **The top bar is pure black chrome**, the one place that's true.
- Light and dark both work: `tokens.css` follows `prefers-color-scheme` via `color-scheme: light
  dark`.
