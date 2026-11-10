# Open Office Harness design system (copied for the apps)

Copied on 10 Nov 2026 from the approved design-system artifact "Open Office Harness" by the spec author. The Workspace and Admin Console copy these files into their builds; the apps never change them. Fonts are under the SIL Open Font License (texts in `licenses/`). Screens to build from are in `docs/design/screens/` (reference HTML exported from the approved design canvas; they load `ds/...` paths and a design-tool script, so they do not render on their own; read their markup and classes). Names and figures in the screens are sample data.

# Open Office Harness

The design system for **open-office-harness**: the staff **Workspace** (chat, files, skills, approvals) and the **Admin Console** (rights, models, skills, audit). One product, two apps, one look.

**Direction:** elegance meets the machine. An elegant serif (the same Bodoni Moda + Inter pairing as faysalaziz.com) carries the human voice; a cyber-tech face carries the interface; mono carries machine output. Dark-first ("Terminal" theme), phosphor green on near-black, with a mild word rain in the background where it helps. A full light theme ("Daylight") exists for bright offices and printing; every token has both values.

## Content fundamentals
- Write like an engineer talking to a colleague: short, direct, active. "Deck ready", not "Your presentation has been successfully generated!".
- Name things by what people recognise: *skills*, *models*, *approvals*, *rights* — never *topics*, *consumers* or *manifests* in the Workspace. The Admin Console may use technical names, with the plain name first.
- Machine output is mono: IDs, model names, token counts, timestamps, file names, request IDs (`req-7f3a…`).
- Errors say what happened and what to do: "You don't have the advanced model (tier 2). An admin can grant it under Rights."
- No emoji. No exclamation marks.

## Visual foundations
- **Ground and surface.** Pages sit on `ground`; panels, cards and chat bubbles on `surface`, separated by a `line` hairline. Depth comes from lines, not shadows.
- **One brand colour.** `phosphor` is the only accent: primary button, active navigation, focus ring, the live "streaming" cursor. Never more than one phosphor button per view.
- **Signals mean state, never decoration.**
  - `signal-cyan`: queued, async, system event (a skill job waiting in Kafka).
  - `signal-amber`: a human is needed (approval pending, tier limit).
  - `signal-red`: denied, failed, dead-letter.
  - Every state also has a text label or icon — colour is never the only signal.
- **Type, four roles, never mixed up.**
  - `serif` (Bodoni Moda): `display`, `h1` only — page titles, the product name, empty-state headlines. Never below 24px, never in tables or buttons.
  - `tech` (Chakra Petch): `label`, `nav`, `stat` — navigation, buttons, eyebrows, status chips, big numbers. Labels uppercase, 0.08em letter-spacing.
  - `sans` (Inter): `h2`, `body`, `small` — everything people read: chat, forms, descriptions.
  - `mono` (JetBrains Mono): `code` — IDs, model names, tokens, timestamps, file names, code.
- **Grid.** Everything on the 4px grid (`space-1`). Cards pad `space-4`; sections sit `space-8` apart.
- **Corners are tight.** `radius-md` (4px) for controls and cards, `radius-sm` for chips, `radius-lg` only for dialogs. No pills except status chips.
- **Motion.** Two signatures only:
  - a blinking block cursor (`phosphor`) while the model streams;
  - **Digital rain** — a mild background of falling character streams: katakana, digits and a few Latin glyphs, a bright glowing head and a fading phosphor trail (see the WordRain component). Only on the sign-in screen, empty states and the Admin Console header band. Never behind text people are reading, never in tables or chat history.
  - Both stop under `prefers-reduced-motion`; word rain also has an on/off setting per user.

## Usage rules
- Text on `ground`/`surface`: `ink` or `ink-muted`. Text on a `phosphor` fill: `on-phosphor`.
- The user's own chat message: `phosphor-soft` fill, `ink` text. The assistant's: `surface` with a `line` edge.
- Inputs: `surface` fill, `line-strong` border, focus ring 2px `phosphor`.
- Tables (audit, rights): `label` style headers in `ink-muted`, rows separated by `line`, IDs in `code`.

## Fonts
All families are open-source (SIL Open Font License) from Google Fonts; the files ship with this system under `fonts/`: Bodoni Moda (variable), Chakra Petch 500 and 600, Inter (variable), JetBrains Mono (variable), and a small Noto Sans JP subset (katakana, digits, capitals) used only by the rain (`rain` family).

## Iconography
Thin 1.5px stroke icons in `currentColor`, square caps, 20px default, drawn on the 4px grid. No filled or coloured icons. (Icon set not yet chosen; Lucide-style stroke icons fit.)

## Logo
None yet — the name in mono at display weight stands in.

## Status
First system (v1): colours, type, spacing, radius, this README. Components: Button, Input, StatusChip, ChatMessage, DataTable, NavRail, WordRain. Styles live in `components/bundle.css` (classes prefixed `ooh-`), built only from tokens.

## Component: Button
Actions, in the tech face: one `primary` per view, everything else `secondary` or `ghost`.

- **Variants:** `ooh-btn--primary` (phosphor fill, the one main action), `--secondary` (outline, `line-strong`), `--ghost` (quiet, cancel/close), `--danger` (revoke, delete — outline in `signal-red`, never a red fill). Size `--sm` for table rows.
- **Labels:** a verb + object, sentence case: "Generate deck", "Approve", "Revoke right". No "OK", no "Submit".
- **States:** `disabled` with a label that says why or what is happening ("Sending…"). Focus ring 2px `phosphor`.
- **Consumer provides:** a `<button>` with `class="ooh-btn ooh-btn--<variant>"` and the label.

## Component: ChatMessage
One turn in the Workspace chat: the user's on `phosphor-soft` (right), the assistant's on `surface` with a `line` edge (left), with a mono meta line.

- `.ooh-msg.ooh-msg--user` or `--assistant` → `.ooh-msg__body` → `.ooh-msg__meta`.
- Meta line (mono): who/tier, time, routing decision with classifier score, request ID — this is how users and admins trace a turn.
- Streaming: end the body with `<span class="ooh-cursor">` until the stream ends.
- Skill jobs appear inside the assistant body as `.ooh-job` (file name + StatusChip) and update in place.
- **Consumer provides:** the text (Markdown rendered to HTML), meta values, any job rows.

## Component: DataTable
Dense admin tables (audit, rights, models, skills): tech-face headers, hairline rows, IDs and times in mono.

- `.ooh-table-wrap` (scrolls sideways on narrow screens) → `table.ooh-table`.
- Use `.ooh-mono` for times, IDs and numbers; StatusChip for outcomes; `ooh-btn--sm` for row actions.
- The example names are illustrative sample data.
- **Consumer provides:** headers and rows.

## Component: Input
Text, select and textarea fields with a tech-face label above and help text below.

- Wrap in `<label class="ooh-field">`: `.ooh-label`, then `.ooh-input` / `.ooh-select` / `.ooh-textarea`, then `.ooh-help`.
- Error: add `ooh-field--error`; the help line becomes the error and says how to fix it.
- Focus: 2px `phosphor` outline. Placeholder is a hint, never the label.
- **Consumer provides:** the label text, the control and an optional help/error line.

## Component: NavRail
The left navigation of both apps: product name in the serif, app name as a phosphor tech label, items in the tech face.

- Active item: `aria-current="page"` (phosphor text, `phosphor-soft` fill, 2px phosphor left edge).
- Counts in mono: amber for things waiting on a human, red for failures.
- Group with `.ooh-nav__section` headings. At phone width, collapse to a top bar (consumer's layout).
- **Consumer provides:** the links, current page, counts.

## Component: StatusChip
The state of a job, request or approval, as a word plus a colour — never colour alone.

| Class | Means | Colour |
|---|---|---|
| `ooh-chip--queued` | Waiting in Kafka for a worker | `signal-cyan` |
| `ooh-chip--running` | A worker is on it (square blinks) | `phosphor` |
| `ooh-chip--approval` | A human must approve first | `signal-amber` |
| `ooh-chip--done` | Finished, result available | `phosphor` |
| `ooh-chip--failed` | Failed, denied or dead-lettered | `signal-red` |

- **Consumer provides:** `<span class="ooh-chip ooh-chip--<state>">Word</span>`. The word is required.

## Component: WordRain

Digital rain: streams of falling characters — katakana, digits and a few Latin glyphs — each with a bright glowing head and a fading phosphor trail. The product's signature motion, kept in the background.

## Where
- Sign-in screen (behind the sign-in card).
- Empty states: a new chat with no messages, an empty approvals inbox.
- Admin Console header band.
- Never behind running text, tables, chat history or forms being filled.

## Rules
- Glyphs: half-width katakana, digits, a few Latin capitals and symbols, in the `rain` family (bundled Noto Sans JP subset, so it renders the same everywhere).
- Look: head glyph in `ink` with a `phosphor` glow; trail in `phosphor`, fading out; a few glyphs flicker inside each stream. Daylight: `ink-muted` trail, `phosphor` head, no glow.
- Strength: the whole layer at 0.6 opacity in Terminal, 0.35 in Daylight (`intensity` option to change it).
- Speed: one step every 55 ms; each column moves every 1–3 steps, so streams fall at different speeds. One column per 18px.
- Pauses when the tab is hidden. Off under `prefers-reduced-motion` (a still frame is drawn instead). Off when the user turns it off in settings.
- Always `aria-hidden="true"` and `pointer-events: none`; it sits under the content on its own layer.

## What the consumer provides
A positioned container. The rain fills it with a `<canvas>` and reads `--phosphor`, `--ink-muted`, `--ground`, `--ink` and `--font-rain` from the page.
