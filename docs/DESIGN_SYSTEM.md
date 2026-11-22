# Transcriber Design System

**Status:** active visual and UI engineering direction  
**Reference:** the focused, content-first desktop aesthetic of the ChatGPT Codex app. Transcriber keeps its own identity and workflows; this is not a pixel-for-pixel clone.

## Design intent

Transcriber should feel like a native, calm desktop workspace for working with audio and text. The interface should make the current recording, transcript, model or task the visual focus. Application chrome should be quiet, controls should be predictable, and color should communicate meaning rather than decorate every element.

### Principles

1. **Content first.** Keep the main canvas visually continuous. Use panels only when they represent a meaningful workspace boundary.
2. **Neutral by default.** Dark and light themes use neutral grays, not blue-tinted surfaces. Primary actions use a high-contrast monochrome fill.
3. **Color has a job.** Blue is reserved for focus, links, active controls and informational states. Green, amber and red communicate success, warning and destructive/error states.
4. **Space before borders.** Separate sections with alignment and spacing. Use thin, low-contrast separators only where structure needs them.
5. **Dense, not cramped.** Use a four-pixel spacing grid and consistent control heights. Avoid oversized cards, excessive padding and decorative headings.
6. **Native and keyboard-friendly.** Preserve Qt interaction conventions, system fonts, accessible names, visible focus, sensible tab order and keyboard shortcuts.
7. **Consistent states.** Every asynchronous page should distinguish idle, loading, progress, success, empty and error states without changing layout unpredictably.

## Color tokens

These are Transcriber's own palette values inspired by the reference direction. They are not copied Codex app tokens.

| Semantic role | Dark | Light | Usage |
|---|---:|---:|---|
| Canvas / `window` | `#181818` | `#FFFFFF` | Main application background |
| Sidebar / `surface` | `#212121` | `#F9F9F9` | Persistent application chrome |
| Raised / `surface_raised` | `#282828` | `#F3F3F3` | Inputs, grouped controls and restrained panels |
| Hover / `surface_hover` | `#303030` | `#EDEDED` | Hovered or pressed neutral surfaces |
| Main text / `text` | `#F3F3F3` | `#1A1C1F` | Primary content |
| Secondary text / `muted` | `#AFAFAF` | `#5D5D5D` | Descriptions, metadata and hints |
| Border / `border` | `#393939` | `#DFDFDF` | Hairline separators |
| Primary action / `primary` | `#FFFFFF` | `#1A1C1F` | Main actions |
| Text on primary / `on_primary` | `#181818` | `#FFFFFF` | Text and icons inside primary actions |
| Accent / `accent` | `#339CFF` | `#339CFF` | Links, selected controls, progress and information |
| Focus / `focus` | `#339CFF` | `#0169CC` | Keyboard focus ring |
| Success / `success` | `#40C977` | `#008635` | Completed and healthy states |
| Warning / `warning` | `#FF8549` | `#E25507` | Caution and pending attention |
| Danger / `danger` | `#FF6764` | `#BA2623` | Errors, destructive actions and recording stop |

**Important:** do not use `accent` as the background of ordinary primary buttons. Use `primary` and `on_primary`. Do not encode state using color alone; pair it with text or an icon.

## Typography

Use the operating system UI font stack: Segoe UI on Windows, Noto Sans where available on Linux, with the normal platform fallback. Do not add a decorative display font.

| Role | Size | Weight |
|---|---:|---:|
| Page heading | 28 px | 600 |
| Section heading | 18 px | 600 |
| Body and controls | 14 px | 400–500 |
| Metadata and helper text | 12 px | 400 |
| Code and time values | 13 px | 400, monospace |

Use medium weights instead of bold-heavy labels. Use tabular numerals for timers, durations, word counts and other values that need stable alignment.

## Spacing and shape

- Spacing scale: 4, 8, 12, 16, 24 and 32 px.
- Corner radii: 4 px for small tags, 8 px for inputs and compact controls, 10 px for rows, 12 px for cards, and 16 px only for large grouped surfaces.
- Prefer a one-pixel, low-contrast border over a strong outline. Do not add shadows to ordinary cards.
- Standard navigation rows should remain around 36–40 px high. Icon-only controls should have a clear hit target and a tooltip/accessibility name.
- Use consistent left alignment for page titles, section headings, tables and toolbars.

## Component patterns

### Application shell
- Keep the sidebar persistent, compact and visually quieter than the active workspace.
- Active navigation uses a neutral raised surface and readable text, not a thick colored rail.
- The top bar belongs to the canvas; separate it with one subtle divider only when necessary.
- Keep the command palette discoverable and keyboard-first.

### Page header
- Use one title and an optional short description.
- Do not add a decorative accent bar beside every page heading.
- Page-specific actions belong on the same row when space allows; move them to a compact action row on narrow layouts.

### Cards and panels
- Reserve cards for a meaningful group: recent work, a model installation task, a settings group, an empty state or a floating tool.
- Avoid nesting cards inside cards.
- Prefer a flat canvas with section spacing for ordinary settings and information.
- A card should not become visually louder than the content it contains.

### Buttons
- **Primary:** one dominant action per page or workflow step; monochrome high contrast.
- **Secondary:** neutral background or transparent surface with a subtle border.
- **Tertiary:** text or icon action with no permanent container.
- **Destructive:** red is reserved for a destructive operation and should be paired with a clear label/confirmation.
- Hover should usually adjust the neutral surface. Blue is for focus and information, not a universal hover color.

### Inputs, lists and tables
- Inputs share the same radius, border, padding and focus treatment.
- Lists are rows, not a stack of outlined cards. Use a subtle hover/selection fill and retain readable spacing.
- Tables use quiet headers and thin row separators. Avoid heavy grid lines and brightly colored selection borders.
- Empty states should tell the user what to do next and provide one relevant action.

### Audio and transcript workspaces
- Audio playback, recording and transcript editing should remain task-focused. Keep timing values aligned and use the waveform as a navigation aid, not decoration.
- Preserve the distinction between local processing and explicitly selected online services.
- Keep destructive transcript operations, recording stop/discard and model removal visually distinct from ordinary navigation.

### AI Assistant
- Treat the conversation as the canvas. Keep controls in a compact composer and settings in a separate surface.
- Keep model/provider selection, local/cloud status, permissions and voice input discoverable without filling the conversation with permanent panels.
- Preserve distinct and accessible Send and Stop controls.

## Design code ownership

- `ui/design/tokens.py` is the only source for palette, typography, spacing, radii and border scales.
- `ui/theme.py` maps semantic tokens to Qt styles. Feature styles must consume the token map; they must not introduce independent color palettes.
- `ui/widgets.py` owns reusable primitives such as `Card`, `page_header`, `primary_button` and section rows.
- Page modules own page composition and behavior. Prefer a stable `objectName` plus a shared QSS rule over one-off `setStyleSheet()` calls.
- Dynamic per-item styling is acceptable only when a state genuinely varies at runtime and cannot be represented cleanly by a shared Qt property.
- Keep domain, audio, transcription, model and persistence code independent of widget styling.

## Architecture review and refactoring order

The domain/service boundaries are a good foundation: transcription engines do not own widgets, the editor document is independent of Qt, and persistence is not implemented inside page widgets. Preserve those boundaries.

The main UI maintainability issue is concentration of unrelated responsibilities in a few large files (snapshot inspected on 2026-11-22):

| Module | Approx. lines | Next responsibility boundary |
|---|---:|---|
| `ui/main_window.py` | 2,254 | Keep shell/navigation here; extract workspace construction, dock coordination and lifecycle/agent wiring into focused collaborators |
| `ui/theme.py` | 1,821 | Keep the public `stylesheet(theme)` entry point; split base, shell, controls and feature styles into composable modules |
| `ui/pages/models.py` | 1,858 | Separate discovery/search, installed models, download tasks and compatibility details into page components |
| `ui/pages/settings.py` | 916 | Compose settings from focused section widgets with shared field/section helpers |

Recommended order:

1. Keep the new semantic token contract stable and remove page-level style literals as pages are touched.
2. Split the large QSS string by feature area without changing the public theme API.
3. Extract the dock/workspace coordinator and agent/IPC integration from `MainWindow`.
4. Break Model Library and Settings into focused widgets while preserving their existing service interfaces.
5. Apply the same page-header, list, form and empty-state patterns across every page.

Do not rewrite the domain architecture to solve a visual consistency problem. Make UI changes at the UI boundary and preserve the existing application services and persistence model.

## Reference direction

- [Introducing the Codex app — OpenAI](https://openai.com/index/introducing-the-codex-app/)
- [Codex desktop design observations](https://codex-design.beacon.host/) — third-party reference, used for visual direction only.
