# Design System — scanst-ui

## Direction
Clean, airy data tool. Inspired by ycharts.com — strong typographic hierarchy, generous whitespace, data readable at a glance. OS-preference aware (light/dark). Blue accent (#2563eb light / #3b82f6 dark). NOT financial-terminal dark — approachable and polished.

## Depth Strategy
**Borders-only.** No decorative shadows on surfaces. Single box-shadow only on modals (elevation above backdrop). This keeps data-dense tables clean.

## Spacing Base Unit
4px. All spacing multiples of 4.

## Token Architecture (CSS custom properties)

```css
/* Light / Dark via @media (prefers-color-scheme: dark) */
--bg-canvas      /* page background: #f1f5f9 / #0f172a */
--bg-surface     /* card/container: #ffffff / #1e293b */
--bg-surface-2   /* table header, input bg: #f8fafc / #263348 */
--bg-surface-3   /* hover states, read-only: #f1f5f9 / #2d3d54 */

--border-subtle  /* row separators: rgba(15,23,42,0.08) */
--border-default /* container borders: rgba(15,23,42,0.14) */
--border-strong  /* emphasis: rgba(15,23,42,0.22) */

--ink-primary    /* #0f172a / #f1f5f9 */
--ink-secondary  /* #475569 / #94a3b8 */
--ink-tertiary   /* #94a3b8 / #64748b */
--ink-muted      /* #cbd5e1 / #475569 */

--accent         /* #2563eb / #3b82f6 */
--accent-hover   /* #1d4ed8 / #60a5fa */
--accent-subtle  /* rgba(37,99,235,0.08) / rgba(59,130,246,0.12) */
--accent-ring    /* focus ring rgba */

--ctrl-bg        /* input/select background */
--ctrl-border    /* input/select border */
--ctrl-focus-shadow /* 0 0 0 3px var(--accent-ring) */
```

## Radius Scale
- `--r-sm: 4px` — inputs, small buttons, chips
- `--r-md: 6px` — buttons, field inputs
- `--r-lg: 10px` — tables, wrappers
- `--r-xl: 14px` — modals, app container

## Typography
- Font: Inter / system-ui fallback
- Headings: 22px, 700, letter-spacing -0.3px
- Table headers: 11-12px, 600, uppercase, letter-spacing 0.05em, `--ink-secondary`
- Body/rows: 13px, 400
- Ticker symbols / numeric values: JetBrains Mono / Fira Code / Courier New fallback, font-variant-numeric: tabular-nums
- Labels in modals: 12px, 600, uppercase, letter-spacing 0.03em

## Button Palette
- **Primary (add/save)**: `--accent` fill, white text
- **Destructive (delete)**: ghost with red tint (`rgba(220,38,38,0.08)` bg, red text) → fills red on hover
- **Action (edit)**: ghost with accent-subtle bg → fills accent on hover
- **Scan/teal**: ghost with teal tint → fills teal on hover
- **Secondary (cancel/import)**: `--bg-surface-2` + `--border-default`, `--ink-secondary` text
- **Disabled**: `opacity: 0.45` universally

## Table Pattern
- Container: `border: 1px solid --border-default; border-radius: --r-lg; overflow: hidden`
- Header row: `--bg-surface-2`, uppercase labels, `--ink-secondary`
- Data rows: `--border-subtle` separators, `padding: 10px 16px`
- Row hover: `--accent-subtle` background
- Grid: `grid-template-columns: 40px 110px 64px 1fr 220px` (tickers table)

## Attribute Pivot Table
- `<table>` with sticky `thead`
- `th`: uppercase, 11px, tabular layout, `--bg-surface-2`
- Value cell: monospace value + muted date below (11px, `--ink-tertiary`)
- Empty cell: `—` in `--ink-muted`
- Click any cell → `AttributeEditModal` (edit or create)

## Modal Pattern
- Overlay: `rgba(0,0,0,0.4)` + `backdrop-filter: blur(3px)`
- Surface: `--bg-surface` + `--border-default` border + soft shadow
- Header: 16px 600 heading + close button (icon, hover bg)
- Field labels: 12px uppercase secondary
- Actions row: border-top separator, right-aligned primary + secondary buttons
- Max-width: 520px (560px for import modal)
