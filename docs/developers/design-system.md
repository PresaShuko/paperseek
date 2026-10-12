# Interface guidelines

The workspace follows a neutral style in the spirit of [shadcn/ui](https://ui.shadcn.com/) (new-york, neutral base), implemented as plain CSS and Vue 3 components. There is no CSS framework or React runtime.

## Where things live

All paths are under `web/src`.

| Layer | Contents | File |
| --- | --- | --- |
| Tokens | Colors, chart palette, radii, shadows, fonts (`--background`, `--muted-foreground`, `--radius-md`, …) | `styles/ui.css` (`:root`) |
| Primitives | Buttons, inputs, selects, cards, badges, tabs, tables, lists, sidebar, stats and bars | `styles/ui.css` |
| Shell and overlays | Scrolling, sidebar collapse, mobile sheet, dialogs, menus, listboxes, toasts, skeletons | `styles/app.css` |
| Fonts | Self-hosted Geist and Geist Mono; Chinese falls back to the system sans-serif | `styles/fonts.css` |
| Shared components | `UiSelect`, `UiMenu`, `UiSheet`, `AppDialog`, `Disclosure`, `StatusBadge`, `Toaster`, `Icon` | `components/` |

## Rules

- Use the tokens; do not hard-code colors, radii, or shadows in a feature.
- Reuse the primitives (`.btn`, `.input`, `.select`, `.card`, `.field`, `.page`, `.hdr`) and the shared components before adding a new class. Add page-specific styles next to the page rather than as overrides at the end of a stylesheet.
- Body text and controls are 14px with 20px line height; metadata is 12px. On screens narrower than 900px, inputs use 16px text so mobile browsers do not zoom.
- The sidebar is 288px and collapses fully; below 900px it becomes a sheet. Only the main inset scrolls; the sidebar history, dialogs, graphs, and bounded lists may scroll on their own.
- Color never carries meaning alone: errors, statuses, and selections also have text or an icon. Network graphs keep categorical colors for node meaning; distribution charts use the blue chart palette.
- Long-form review text keeps a reading size and line height instead of the denser card style.
- The workspace has a light theme only.

PaperSeek online builds on the same web sources, so visual changes belong in Community.

## Checking a change

Run `npm run typecheck`, `npm run build`, and `npm run test:browser` in `web/`, then look at the change in a real browser at desktop and phone widths.
