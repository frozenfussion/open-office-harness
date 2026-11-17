# Stage 5 — Pictures in chat, and export a chat to Word

Written 2026-11-17 by Claude (orchestrator), live in class. Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Claude tags that commit `stage-5-base` and pushes the tag from harness.
**Tag:** `pictures-and-export` when Aziz accepts the stage.

## 0. Aziz's words and decisions (Malaysia time, 17 Nov 2026)

- 09:23: "I want to add two small features to this harness right now. The first feature is multimodality, which means image recognition. Let's keep it simple for now. And the second thing I want to do is export the chat." Order of work: discussion, a mock-up, the tech cost, then the spec.
- 09:27: "Let's just export it as docx. I think that's the simplest thing." Pictures go to the chat models already configured: "that way we do not have to create any more moving parts. What we have should be good enough."
- 09:38, answers to four questions put to him with options: (1) a separate "multimodality" permission is the **next step**, not this stage; (2) the Word file is made **in the Harness**, not in the browser and not as a skill on Kafka; (3) it contains the **questions and answers**, without the Thinking sections; (4) the model **keeps seeing** a picture in follow-up questions.
- 09:44: no 5 MB limit; he asked for 50 MB. 09:47, after the providers' limits were shown to him (Claude API 10 MB per picture once base64-encoded, DeepSeek 32 MiB per picture and 48 MiB per request, OpenAI 512 MB per request): of three options he chose **"lower the limit instead"**: the largest size all three accept as it is, no shrinking anywhere.
- 09:50: the mock-up "looks good"; go ahead with the spec. "When you do the checking in the terminal, make sure everything is shown. I need my students to view everything that happens in the terminals."
- Tiles: on 15 Nov 05:25 the tmux window was tidied at his request to one Shell tile; live class brief of 17 Nov, section 4.4: "Existing tile numbers never change; add tiles, do not renumber." The tile list in section 3 follows that, and the sentence about tiles in the global rules is updated in this pull request.
- 10:11, after the spec review: "Let's keep it simple. Since this is for us internal use, it's all right for the phone and location data to be there." The check script prints PASS or FAIL lines.
- Standing: nothing about AI providers is hard-coded (10 Nov 13:32); no new technology unless it solves a real problem; the simplest step that does not cut corners.

## 1. Purpose

**A picture in the chat.** A person attaches one picture (PNG or JPEG, at most 7 MiB) to a chat message in the Workspace. The picture is stored on the files volume, shown inside the person's message, and sent with the question to the chat model of the chosen tier through the Model Gateway. The model answers about it. The picture stays in view for follow-up questions in the same conversation (section 4, "Pictures in view"). No new service, no new topic, no separate vision model: the three connection types each learn to carry a picture.

**Export a chat to Word.** A button in the chat header downloads the open conversation as a `.docx` file made by the Harness: the title, when the conversation started and when it was exported, and each question and answer with its time and the model that answered. Markdown formatting is kept. The export is recorded in the audit trail.

## 2. Done when (all of these)

1. GitHub Actions builds all nine images for one commit, tagged with its first 12 characters; all pull without signing in.
2. On harness, from the merged `stage-5` worktree, every script in the README order (section 10) ends with `DONE`. Claude runs them in the Shell tile where the class watches; none needs sudo. All pods in `ooh-apps` are Ready.
3. `install/87-check-stage-5.sh <tag>` prints `PASS` for every line and ends with `DONE` (section 9); `40`, `62`, `70` and `77 <tag>` still pass. `78` is not run in class (it stops chat); it is run before the next acceptance that needs it.
4. In the browser (Aziz):
   (a) attach a PNG, ask about it: the picture shows in his message and the answer describes it;
   (b) a follow-up question about something in the picture that the first answer did not mention is answered from the picture;
   (c) the same with a JPEG, and once on each of the three chat tiers;
   (d) a file over 7 MiB, and a file that is not a PNG or JPEG, are refused in the chat box with a plain message and nothing is sent;
   (e) after reloading the page the picture is still in the conversation;
   (f) **Export to Word** downloads a `.docx` that opens in Word with the title, the date, every question and answer with its time and model, headings, lists, a table and a code block formatted, no Thinking text, and "[Picture attached: <file name>]" where a picture was;
   (g) Admin Console, Audit: one row for the upload and one for the export;
   (h) a picture just under 7 MiB is answered on each of the three tiers, and on tier 1 a follow-up is answered with three such pictures in view (the largest request this stage allows).
5. In a clean worktree of `stage-5`: every Part's checks pass; `uv run --project contracts/check pytest contracts/check/tests` passes; `bash -n` and `shellcheck -x` are clean for `install/*.sh install/lib/*.sh`; `kubeconform -strict` passes on `deploy/`.
6. `README.md` Quick Guide covers section 10; `docs/STATUS.md` says Stage 5 is done and lists what was checked; `docs/ARCHITECTURE.md` and `contracts/storage.md` describe what was built.
7. No reboot test in class (Aziz, handover of 15 Nov: the Droplet is not rebooted during class). It is carried to the next acceptance.

## 3. Prerequisites

1. Tiles in tmux session `harness`, window `work`. Existing tiles keep their numbers: 0 SHELL, 1 CODEX (SpecDev, not used here). Added for this stage: 2 CLAUDE CODE (reviewer), 3 CODEX A, 4 CODEX B, 5 CODEX C.
2. The contract change in section 6.1 is in this spec's pull request.
3. No new database. Part B adds one migration to the Harness database (owner role, init container, as before).
4. No real model, no Kafka and no real files volume in unit tests: the Gateway is faked with respx as today; Kafka with the existing fakes; files in a temporary folder.
5. The three chat models already entered in the Admin Console accept pictures. Read on 17 Nov 2026 in each provider's own documentation (links in section 4, "Provider limits"): model IDs `deepseek-flash`, `gpt-6.1-sol`, `claude-opus-5-5`. Not yet tried with our keys: section 12.

## 4. Decisions for this stage (fixed; versions checked 17 Nov 2026 on pypi.org)

| Item | Decision | Why |
|---|---|---|
| Which model reads a picture | the chat model of the tier in use, through `/v1/call`; no purpose, tier or model entry is added | Aziz 09:27: no more moving parts. All three configured models accept image input |
| Permission | none in this stage: a person who may chat on a tier may attach a picture on it. The decision "may this person attach a picture" is one function in the Harness (`may_attach`, section 8) that returns true | Aziz 09:38 (1): the next step. One place to add the right later |
| File types | PNG and JPEG only, by the first bytes of the file (PNG `89 50 4E 47 0D 0A 1A 0A`; JPEG `FF D8 FF`), which must agree with the request's `Content-Type` | All three providers accept both; a wrong label is refused before it is stored |
| Provider limits (read 17 Nov 2026) | Claude API: 10 MB per picture once base64-encoded, 128 MB per request, larger pictures are shrunk by the provider to 2,576 px on the long side (https://platform.claude.com/docs/en/build-with-claude/vision). DeepSeek: 32 MiB per picture, 48 MiB per request body; `deepseek-flash` accepts pictures (https://api-docs.deepseek.com/guides/vision). OpenAI: 512 MB total payload per request; `gpt-6.1-sol` lists image input (https://developers.openai.com/docs/guides/vision, https://developers.openai.com/api/docs/models/gpt-6.1-sol) | The numbers every limit below is taken from. Smallest per picture: Claude, 10 MB encoded. Smallest per request: DeepSeek, 48 MiB |
| Size limit | setting `HA_UPLOAD_MAX_BYTES`, value **7340032** (7 MiB), in the Harness ConfigMap. The Workspace reads it from `/api/me`. The value must be a whole number of MiB from 1 to 7 (a multiple of 1 048 576, at most 7 340 032): the Harness refuses to start with any other value, and says why in its log. It can be lowered, never raised: the Gateway's own cap (section 6.3) is fixed at the 7 MiB figure. Every message and help line shows the limit as bytes divided by 1 048 576, with "MB" | Aziz 09:47. 7 MiB is 9 786 712 characters as base64, under the smallest per-picture limit (10 MB encoded) |
| Shrinking | none, in the browser or on the server; no image library | Aziz 09:47 |
| Pictures per message | at most one | Aziz 09:23 "keep it simple"; shown in the mock-up he approved |
| A picture needs text | yes: the message text stays required | One rule for every message; the title and the routing question read the text |
| Upload format | the picture is the raw request body of `POST /api/uploads`, with `Content-Type: image/png` or `image/jpeg` and the file name in the header `X-File-Name` (percent-encoded UTF-8, optional). Not `multipart/form-data` | No form-parsing library: global rules section 4 ("no dependency for something the language already does"). This changes the upload contract (section 6.2) |
| Where pictures are kept | the existing volume `ooh-files`, key `uploads/<upload id>/<safe file name>`. The Harness mount becomes read-write. The Harness writes **only** under `uploads/` (a path check with a test) through a temporary name and a rename, as the Slides worker does | The contract for files (v2) already puts files there. The write pattern is the one the Slides worker has proven on this volume, and both run as user and group 10001, so `uploads/` gets the same owner as `outputs/`. One mount, no sub-mount: nothing new in the manifests to go wrong |
| Nothing is deleted | an upload that is never sent stays; `uploads` has `deleted_at` and no delete route | Global rules |
| Upload limit per person | setting `HA_UPLOADS_PER_DAY`, value **20** per UTC day; then 429 | The volume is 20 Gi, shared with Slides output, and nothing is deleted. 20 pictures of 7 MiB are 140 MiB per person per day at the very most. The limit slows filling the disk; it does not prevent it (section 13) |
| Pictures in view | for a model call the Harness takes the last 20 messages, as today, plus the message being sent. The answer to a user message is the next message in the conversation (by `created_at`, then `id`), read from all rows, not from the history query (which leaves failed answers out). Among the user messages in that last-20 window plus the message being sent, the candidates are those with a picture whose answer has outcome `completed`; the message being sent always qualifies. The **three newest** candidates get their picture attached. Every other picture is not sent and its message goes as text only | Aziz 09:38 (4). Three pictures of 7 MiB are 29.4 MB as base64, under DeepSeek's 48 MiB request body, the smallest of the three. A picture the model refused, or whose answer failed, is never sent again, so one unreadable picture cannot block a conversation |
| How the Gateway gets a picture | the Harness reads the file and sends it inside the `/v1/call` JSON as base64 (section 6.3). The Gateway does not mount the files volume | A module talks to another only through a contract |
| Memory | memory limits of `harness-api` and `model-gateway` go from 512Mi to **2Gi** (requests unchanged). Sized for a class: a call with three 7 MiB pictures holds about 90 MB in each service while it streams, so about 15 such calls at once fit; ordinary pictures are far smaller. More at once than that can restart a pod: a known limit (section 13) | A call with pictures is held in memory in both services for the length of the stream |
| Provider says no to the picture | a provider answer 400, 413 or 422 **before the first output**, to a call that carries a picture, is error `image_refused`. It does **not** mark the model entry down; the backup entry is still tried. If no entry succeeds and at least one attempt in the call ended in a picture refusal, the call's error is `image_refused`, whatever the other attempts failed with. The existing one retry after a 400 on a forced tool happens first: only if that retry is also refused is the attempt a picture refusal | Otherwise one unreadable picture would show a healthy model as down in the Admin Console |
| Auto routing, titles, safety watcher | unchanged: they read the message text only. `chat.message` on Kafka is unchanged and carries no picture | Known limit, in section 13 |
| Logs, traces, audit, Kafka | never picture bytes, base64 or the file name. Audit rows carry the MIME type only. No new span attribute. The picture is stored and sent exactly as uploaded, including any hidden details a camera wrote into it, such as the place it was taken (section 13) | Global rules section 4; the Stage 4 allow-list stays as it is |
| Export: where and how | `GET /api/conversations/{id}/export` in the Harness builds the file in memory and returns it. Direct HTTP, no job, no Kafka | Aziz 09:38 (2). The work takes well under a second; Kafka does not earn its place |
| Export: Word library | **python-docx 1.2.0** (brings lxml 6.1.3 and typing-extensions, both already used by the Slides worker's python-pptx; pinned in the lock file) | The standard library for writing `.docx`; same family as python-pptx |
| Export: reading Markdown | **markdown-it-py 4.3.0** (brings mdurl 0.1.2), used only as a parser to tokens (the `commonmark` preset with `table` and `strikethrough` switched on); nothing is rendered to HTML | Answers are Markdown. A hand-written Markdown reader would be the riskiest code in the stage. A second new library; told to Aziz |
| Export: what is in the file | section 6.2 "Export", exactly | Aziz 09:38 (3) and the mock-up |
| Export: times | shown in the time zone of setting `HA_DISPLAY_TIME_ZONE`, value `Asia/Kuala_Lumpur`, as `17 Nov 2026 09:52`; the line under the title also shows the zone's short name (`+08`) | Global rules: times are stored in UTC, the display zone is a setting |
| Images built and deployed | all nine images for the merge commit, deployed with one tag | Checks `77` and later ones expect one tag everywhere |

## 5. Data

**Harness (`harness`), new migration `0005_uploads.sql`** (never edit an applied one):
- `uploads` (business table, standard columns and `deleted_at`, with the `refuse_removal` trigger, as `jobs`): `id uuid` primary key, `user_id text`, `file_name text` (1 to 100 characters), `mime text` CHECK (`image/png`, `image/jpeg`), `size_bytes integer` CHECK (> 0), `sha256 text` (64 lower-case hex), `file_key text` unique. Index (`user_id`, `created_at`).
- `messages` gains `upload_id uuid null` REFERENCES `uploads(id)`, with a unique index on `upload_id` where it is not null (a picture belongs to one message). Existing rows keep null.

No other service's data changes.

## 6. Interfaces

### 6.1 Contract change in this spec's pull request (spec author; the Parts read, never change it)

- `contracts/storage.md` becomes v3: new row "Chat picture | `uploads/<upload id>/<safe file name>`"; the Harness mounts the volume read-write and writes only under `uploads/`; pictures are read back only through `GET /api/uploads/{upload_id}` by their owner; the line "Uploads remain unbuilt" is removed.

### 6.2 Harness API (Part B updates `contracts/http/harness-api.openapi.yaml` and its examples)

- **`POST /api/uploads`** (bearer). Request: raw body, `Content-Type` `image/png` or `image/jpeg` (parameters after a `;` are ignored; `image/jpg` and everything else is `unsupported_type`); optional header `X-File-Name`. The body is read as a stream and reading stops at the limit plus one byte. The checks run in this order, and the first that fails answers: token (401); `Content-Type` (400 `unsupported_type`); today's count (429); empty body (400 `invalid_input`); first bytes against the `Content-Type` (400 `unsupported_type`); size (413); write (503).
  - 201 `{upload_id (uuid), file_name, mime, size_bytes}`. `file_name` is the safe name: the percent-decoded header value, the part after the last `/` or `\`, characters outside `[A-Za-z0-9._ -]` replaced by `_`, leading dots and spaces removed, the extension removed and `.png` or `.jpg` added by the detected type, the stem cut so the whole name is at most 100 characters. If there is no header, the header cannot be decoded as UTF-8, or the stem is empty after these steps, the name is `picture.png` or `picture.jpg`. A bad header never refuses an upload.
  - 400 `unsupported_type` "Only PNG and JPEG pictures can be attached." (the `Content-Type` is neither, or the first bytes do not match it); 400 `invalid_input` (empty body); 413 `too_large` "This picture is larger than the limit of <n> MB." (`<n>` from the setting, section 4); 429 `upload_limit` "You have reached today's limit for pictures."; 503 `storage_unavailable` (the file cannot be written; nothing is recorded); 401 as every route.
  - Writes `<files root>/uploads/<upload_id>/<file_name>` through a temporary name in the same folder, then the `uploads` row, then publishes `audit.event` `{actor: user_id, action: "upload.created", target: <mime>, outcome: "ok"}` with a new `correlation_id` (a publish failure is logged with ids only and never fails the upload).
  - The old answer 503 `not_built_yet` is gone.
- **`GET /api/uploads/{upload_id}`** (bearer): 200 the bytes with the stored `Content-Type` and `Cache-Control: private, max-age=3600`, with `X-Content-Type-Options: nosniff` and `Content-Disposition: inline`, when the upload belongs to this user; else 404, also when the file is missing on disk. Malformed id 400. The resolved path must stay under `<files root>/uploads/`, symlinks refused.
- **`POST /api/conversations/{id}/messages`**: the body gains optional `upload_id` (uuid). When present: the upload must belong to this user and not be attached to a message yet, else 404 `upload_not_found` or 409 `upload_used`; `may_attach` must allow it (else 403 `not_allowed`). **All of these checks run before the user message is stored and before any call that costs money.** The user message is stored with `upload_id`; if the unique index on `messages.upload_id` refuses the insert (two sends at once), the answer is 409 `upload_used`, not 503. `content` stays required. Everything else in this route behaves as today, including Auto routing on the text, with one change: if the second rights check on the budget fallback fails (the question is already stored by then), the answer is 503 `unavailable`, never `rights_unavailable` or `tier_not_allowed`, so those two codes always mean "nothing was stored".
- **History for the model:** `database.history` also returns `upload_id` for user rows. The Harness attaches pictures as section 4 "Pictures in view" says, the message being sent included (today the route reads the history before it stores the new message and appends the new one by hand; the picture goes on that appended item too). The same list is used on the budget fallback call. For each picture in view, the message item gets `images: [{media_type, data}]` (section 6.3), read from the file at call time. A picture file that cannot be read is skipped and logged with ids only; the call still goes. Tool rounds reuse the same history, pictures included.
- **Model could not read the picture:** Gateway error `image_refused` reaches the browser like other Gateway errors, as code `image_refused`, HTTP status 502 when it is the first event, message "This model could not read the picture. Try another model." The assistant message is stored with outcome `failed`, as for other Gateway errors, so that picture is not in view again.
- **`GET /api/conversations/{id}`**: every message gains `picture`: `{upload_id, file_name, mime, size_bytes}` or null.
- **`GET /api/me`** gains `upload_max_bytes` (integer).
- **Export: `GET /api/conversations/{id}/export`** (bearer): 200 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Content-Disposition: attachment; filename="<slug>.docx"` where `<slug>` is the conversation title in lower case with every run of characters outside `[a-z0-9]` replaced by `-`, trimmed, at most 60 characters, or `chat` when empty. 404 when the conversation is not this user's; 400 malformed id. Then `audit.event` `{actor: user_id, action: "conversation.exported", target: "docx", outcome: "ok"}`, `correlation_id` = the conversation id. A failure to publish, or Kafka being switched off, is logged with ids only and never fails the export.
  The file, in this order:
  1. The conversation title as the document title (style Title).
  2. One line: `Open Office Harness · conversation started <time> · exported <time> (<zone short name>)`.
  3. For every message with `outcome` `completed` and non-empty content, oldest first: a label line, **You** or **Assistant**, followed by ` · <time>` and, for the assistant, ` · tier <n> · <model title>` when stored; then the message body.
  4. A user message with a picture gets a last line `[Picture attached: <file name>]`. The picture itself is not put in the file.
  5. Never in the file: Thinking text, reasoning state, routing notes, token counts, user ids, the person's name or email.
  **User** message bodies are written as plain paragraphs with every line break kept, exactly as typed (the Workspace shows them as plain text too). **Assistant** message bodies are parsed with markdown-it-py (section 4) and written as: paragraphs; headings levels 1 to 3 as Word headings 2 to 4, deeper levels as heading 4; bold, italic, strikethrough, inline code (a monospace font); bullet lists with Word's List Bullet styles, nested up to three levels; numbered lists as indented paragraphs whose text starts with the Markdown's own number and a full stop (`3.`), so every list keeps its own numbers and no Word numbering is used; fenced and indented code blocks as monospace paragraphs with line breaks kept; tables as Word tables with a header row; block quotes as indented paragraphs; a link as its text followed by the address in brackets; a horizontal rule as an empty paragraph. Raw HTML and LaTeX stay as the typed characters. Characters XML does not allow are removed.
- `POST /api/uploads` and both new GET routes need a valid token and have tests, as every route.

### 6.3 Model Gateway (Part A updates `contracts/http/model-gateway.openapi.yaml` and its examples)

- **`/v1/call` messages:** a message with role `user` may carry `images`: an array of **at most one** item `{media_type: "image/png" | "image/jpeg", data: <base64, 1 to 9786712 characters>}`, no other fields. `images` on any other role, more than **three** messages with `images` in one call, or `data` that is not valid base64, is 400 `invalid_input`. A message with `images` still needs non-empty `content`. The length cap on `data` is fixed in the Gateway, not a setting.
- **Adapters** send the picture in the provider's own shape, text and picture in one user turn:
  - `openai_chat_completions`: `content` becomes `[{"type":"text","text":<content>},{"type":"image_url","image_url":{"url":"data:<media_type>;base64,<data>"}}]`.
  - `openai_responses`: the user item's `content` becomes `[{"type":"input_text","text":<content>},{"type":"input_image","image_url":"data:<media_type>;base64,<data>"}]`.
  - `anthropic_messages`: `content` becomes `[{"type":"image","source":{"type":"base64","media_type":<media_type>,"data":<data>}},{"type":"text","text":<content>}]`.
  A message without `images` is sent exactly as today. The builder checks each shape against the provider's official reference on the day and reports any difference; the behaviour in this section does not change without a row in section 14.
- **`image_refused`:** as section 4, including which code the caller gets when several entries were tried. The streamed `failed` event and the non-streamed error carry code `image_refused`; HTTP status as for `unavailable` today. Audit event outcome `failed` as today.
- **Classification (`/v1/classify`), the Jev connection, health reports for every other failure, cost, rate limits, budgets, tracing:** unchanged. Picture tokens arrive in the provider's usage figures and are costed like any input tokens.
- Never log, trace or publish `data`.

### 6.4 Workspace (Part C)

Follows the mock-up Aziz approved on 17 Nov ("Workspace mock-up: picture in chat and Export to Word", three screens) and the design system tokens; no new colour or font.
- **Chat box:** a button **Attach picture** (a real `<button>` opening a hidden file input that accepts `image/png,image/jpeg`), and the help line "PNG or JPEG, up to 7 MB, one per message · Enter to send · Shift+Enter for a new line" (the number comes from `upload_max_bytes`). Choosing a file checks type and size in the browser first, then uploads it; while uploading, Send is disabled. A preview shows the picture small, its file name, type and size, and a **Remove picture** button (removing only forgets it in the browser). One picture at a time: choosing another replaces it. Refusals show in the existing notice line with the API's message.
- **Sending:** `upload_id` goes with the message. The user message added to the screen at once shows the picture from the preview's own copy, without a fetch. What happens next depends on whether the server stored the message. **Stored** (the stream starts, or the refusal is any code not listed next, for example `image_refused`, `rate_limited`, `budget_exceeded`, `no_model`, `unavailable`): the preview clears, the question stays on screen, and the notice shows the API's message; to try again the person attaches the picture again. **Not stored** (refusal codes `invalid_input`, `not_found`, `upload_not_found`, `upload_used`, `not_allowed`, `no_tier`, `tier_not_allowed`, `rights_unavailable`, `unauthorized`): the question just added to the screen is removed and the text goes back into the box; the preview stays, except on `upload_used`, where it clears with the notice "This picture was already sent. Attach it again to send it once more."
- **In the conversation:** a user message with `picture` shows the picture above its text, fetched from `GET /api/uploads/{upload_id}` with the bearer token as a blob and shown through an object URL (released when the message leaves the screen), with the file name as its caption and as the image's `alt` text. The model-output sanitiser is not changed: `img` stays forbidden in rendered Markdown.
- **Export to Word:** a button in the chat header, left of the model picker. Disabled while there is no saved conversation with at least one message, and while an answer is streaming. It downloads with the bearer token as a blob, as the Slides download does; the file name comes from `Content-Disposition`, else `chat.docx`. Afterwards a status line says "Saved: <file name>".
- If a Content-Security-Policy applies to the Workspace anywhere in the repo, it must allow `img-src blob:`; the builder checks and reports.

## 7. Parts

Three Codex windows at the same time, each in its own worktree from `stage-5-base`. **No Part changes a file another Part lists.** Nobody changes the files in section 11. The split is by service, not by feature: both features need the same Harness files and the same Workspace screen, so a split by feature would put two builders in one file.

### Part A — Model Gateway (branch `stage-5-part-a`, Codex A, tile 3)
```
services/model-gateway/**
contracts/http/model-gateway.openapi.yaml
contracts/examples/http/model-gateway.*
contracts/examples/index.model-gateway.json
deploy/apps/model-gateway/*.yaml                 (memory limit)
```

### Part B — Harness API (branch `stage-5-part-b`, Codex B, tile 4)
```
services/harness-api/**                          (migration 0005, uploads, pictures in history, export, tests, README, pyproject.toml, uv.lock)
contracts/http/harness-api.openapi.yaml
contracts/examples/http/harness-api.*
contracts/examples/index.harness-api.json
contracts/examples/index.json                    (the /api/uploads entries only)
contracts/README.md                              (the paragraph about POST /api/uploads only)
deploy/apps/harness-api/*.yaml                   (volume read-write, memory limit, new settings)
install/67-harness-api-deploy.sh                 (only if it must change)
```

### Part C — Workspace, stage check, documents (branch `stage-5-part-c`, Codex C, tile 5)
```
apps/workspace/**
deploy/apps/workspace/*.yaml                     (only if it must change)
install/87-check-stage-5.sh
README.md
docs/ARCHITECTURE.md
```

**Checks for every Part:** as Stage 4 for each package it owns (Python: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest`; Angular: `npm ci`, `npx ng build`, `npx ng test --watch=false`); the contract check; `bash -n` and `shellcheck -x` for its scripts; `kubeconform -strict` for its manifests.

**Tests each Part must have, at least:**
- A: the final error code when the main entry refuses the picture and the backup refuses, is down, is rate-limited or is over budget; a forced-tool call with a picture; for each of the three adapters, a call with a picture produces exactly the shape in 6.3 and a call without one is byte-for-byte what it was; each `invalid_input` case: `images` on a role other than `user`, two items in one `images`, an extra field in an item, a `media_type` other than the two, `data` that is empty, too long or not base64, a fourth message with `images`, and `images` with empty `content`; `image_refused` on 400, 413 and 422 with a picture, with health unchanged and the backup tried; the same statuses without a picture behave as today; no `data` in any log record.
- B: upload accepted (PNG, JPEG); each refusal in 6.2; every file-name case in 6.2; the checks run before anything is stored (no message row and no Gateway call after a refused `upload_id`); two sends of one upload at once give one 200 stream and one 409; the start-up refusal of a bad `HA_UPLOAD_MAX_BYTES`; the order of the upload checks; the answer rule and the choice of three in "Pictures in view" (a failed answer, an empty answer, four pictures, a picture outside the last 20); a second numbered list keeps its own numbers; a picture whose answer failed is not in view; the message being sent carries its picture; user text with `*`, `#` and single line breaks comes out unchanged in the export; the export time line shows the zone; a write outside `uploads/` is impossible (path with `..`, absolute name, symlink); another user's upload is 404 on read and on attach; an upload used twice is 409; history carries at most three pictures and the right three; a missing picture file is skipped; the export file opens with python-docx in the test and holds the title, both labels, the model line, the picture line, a heading, a nested list, a table and a code block, and holds no Thinking text; the slug rules; both audit events.
- C: the attach flow (accept, refuse by type, refuse by size, replace, remove, upload error); the message with a picture; the Export button's enabled and disabled states and the download.

### Merge, deploy, check
Claude makes `stage-5` from `stage-5-base` in `~/projects/worktrees/stage-5`, merges A, B, C and any spec-rows branch, runs every check of section 2 item 5 on a clean worktree, writes the Stage 5 section of `docs/STATUS.md`, pushes `stage-5` (after Aziz's yes), starts all nine image workflows for the merge commit, deploys in the README order and runs the checks. Every command runs in a tmux tile the class can see.

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Upload | `POST /api/uploads` (raw body; headers `Content-Type`, `X-File-Name`) → `{upload_id, file_name, mime, size_bytes}`; `GET /api/uploads/{upload_id}` |
| Message body | optional `upload_id` |
| Conversation message | `picture`: `{upload_id, file_name, mime, size_bytes}` or null |
| `/api/me` | `upload_max_bytes` |
| Export | `GET /api/conversations/{id}/export`; MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| Gateway message | `images`: `[{media_type, data}]`, at most one per message, at most three messages per call |
| Error codes | Harness: `unsupported_type`, `too_large`, `upload_limit`, `storage_unavailable`, `upload_not_found`, `upload_used`, `not_allowed`; Gateway and Harness: `image_refused` (Harness HTTP 502) |
| Settings | `HA_UPLOAD_MAX_BYTES` `7340032`; `HA_UPLOADS_PER_DAY` `20`; `HA_DISPLAY_TIME_ZONE` `Asia/Kuala_Lumpur` |
| Audit actions | `upload.created` (target = the MIME type), `conversation.exported` (target `docx`) |
| Storage key | `uploads/<upload_id>/<file_name>` |
| One place for the permission | Harness function `may_attach(user_id, rights) -> bool`, returns true in this stage |
| Script | `install/87-check-stage-5.sh <tag>` |

## 9. `install/87-check-stage-5.sh <tag>` (Part C), one `PASS`/`FAIL` line each, then `DONE`

Uses `install/lib/stage-check.sh` as `78` does (lock, temporary check client, tokens never printed). It stops no service. The test picture is a PNG, 64 by 64, its left half red (`#FF0000`) and its right half blue (`#0000FF`), embedded in the script as base64.
1. Every Deployment in `ooh-apps` runs `:<tag>` and is Ready.
2. Upload the test picture as the check user → 201 with an `upload_id`; `GET /api/uploads/{upload_id}` returns the same bytes (compared by SHA-256).
3. For each chat tier that has an active main entry: a new conversation, one message "What colour is the left half of this picture? Answer with one word." with the picture (tier 1 uses the upload of item 2; each other tier a fresh upload), stream read to its end → the answer contains `red`, ignoring case, and the tier 1 answer does not contain `blue`. The tier is granted to the check user for the run and removed on every exit, as `77` does.
4. In the tier 1 conversation, a second message without a picture: "And the right half? One word." → the answer contains `blue`. The first answer never said blue, so only the picture still in view can give it.
5. Refusals: text bytes sent as `image/png` → 400 `unsupported_type`; a body of the limit plus one byte, made of the PNG signature followed by padding and sent as `image/png` → 413 `too_large`; a message with an unknown `upload_id` → 404 `upload_not_found`; an upload already sent in item 3, attached to a second message → 409 `upload_used`.
6. `GET /api/conversations/{id}/export` for the tier 1 conversation → 200 with the Word MIME type; the body starts with `PK`; unpacked on harness by the script (Python's `zipfile`; no pod is needed), the text of `word/document.xml`, with the `w:t` pieces of each paragraph joined, contains the first question's text, `[Picture attached:` and `exported` followed by a time and `+08` (this proves the time zone works in the deployed image).
7. The audit trail holds `upload.created` and `conversation.exported` for the check user from this run (the script waits up to 60 seconds for both, as `78` does).
8. No pod log in `ooh-apps` since the run started contains a 40-character slice taken from the middle of the test picture's base64 (its image data, not its header). The script reads `kubectl logs --since-time=<run start>` for every pod on harness into a variable and searches it; the log text itself is never printed.
9. `ooh-stage-check` is disabled again.
Each run makes a few short paid calls (one per tier and one follow-up) and uses one of the check user's 20 daily pictures per chat tier (three today), so six runs fit in one UTC day (a UTC day starts at 08:00 Malaysia time); on a seventh, item 2 prints `FAIL daily picture limit reached for the check user, try after 08:00 Malaysia time`. The README says both.

## 10. README Quick Guide additions (Part C)
1. Stage 5 order: 61 → 65 → 67 → 73 → 75 → 68 → 69 → 40 → 62 → 70 → 77 → 87 (no new setup script, no new secret).
2. Attaching a picture: the limit, the two file types, where pictures are kept, that nothing is deleted, the daily limit, and how to change the three settings (edit the ConfigMap file, redeploy with 67).
3. Which model reads a picture: the chat model of the tier; what `image_refused` means and what to do (the model entry does not accept pictures: choose another model for that tier in the Admin Console).
4. Export to Word: what is in the file and what is left out.
5. Known limits (section 13), in plain words.
6. Every new `STOP:` and `FAIL` and what to do.

## 11. Files that already exist (spec author's; Codex does not change them)
`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, `docs/plan/*`, `docs/images/*`, `docs/design/*`, `docs/routing/*`, `docs/STATUS.md`, `docs/OVERVIEW.md`, `apps/design-system/*`, `contracts/check/*`, `contracts/events/*`, `contracts/skills/*`, `contracts/storage.md`, `contracts/identity.md`, `contracts/README.md` (except the one paragraph Part B owns), `contracts/examples/index.json` (except the entries Part B owns), `install/lib/*`, and every earlier file not listed in a Part. If a Part believes one must change, it stops and asks with the reason.

## 12. Pre-mortem and unverified

| Step | Failure | How it shows | Action |
|---|---|---|---|
| A provider's picture shape differs from 6.3 | 400 from the provider | `image_refused` on that tier; item 3 fails for that tier | the builder checks the provider's reference on the day; item 3 runs every tier |
| A configured model does not accept pictures after all | 400 | `image_refused`; item 3 | UNVERIFIED with our keys until item 3 runs. Fix is data: another model for that tier in the Admin Console |
| The Harness cannot write to the volume | 503 `storage_unavailable` | item 2 fails | UNVERIFIED live: the Harness has only read this volume so far. It runs as the same user and group as the Slides worker, which writes there. If it fails, stop and ask; do not change ownership by hand |
| Large request bodies between Harness, Gateway and provider | slow or refused calls; a pod restarts (OOMKilled) | chat errors; pod restarts in `kubectl get pods` | three pictures at most, 2Gi limits; section 2 item 4 (h) sends the largest allowed request |
| The ingress limits request size | 413 from Traefik, not from the Harness | upload fails with an HTML or empty error | UNVERIFIED: no limit is configured in the repo; item 5 sends the limit plus one byte and expects the Harness's own 413 |
| A time zone name is not known inside the image | export fails | 500 on export | UNVERIFIED until deployed: `87` item 6 proves it in the running pod. If it fails, stop and ask before adding anything |
| Markdown the parser reads differently from the Workspace | formatting differs between screen and file | visual only | the file is a record of the text; no content is dropped: unknown tokens are written as plain text |
| The send is refused before the message is stored (the codes named in 6.4) | an unused upload | — | the text stays; the preview stays, except on `upload_used`, where it clears and the person attaches the picture again |
| The model fails after the message was stored | the picture is used and not in view | — | the person attaches it again (a new upload); the old one stays on disk (nothing is deleted) |
| A provider's limit in section 4 is out of date | 400 from the provider on a large picture | `image_refused` | section 2 item 4 (h) tries the largest size on every tier before acceptance; the fix is the setting (lower it) |
| Two builders need the same file | a merge conflict | — | the Part rule; the split is by service |
| Routing sends a picture question to tier 1 because the text looks easy | a weaker answer | — | known limit; the person can choose the model |

## 13. Out of scope for this stage
A "multimodality" permission and its Admin Console screen (the next step); more than one picture per message; other file types (PDF, GIF, WebP, documents); shrinking or converting pictures; drag and drop and paste from the clipboard; making or editing pictures; the safety watcher and Auto routing reading pictures; the picture inside the Word file; exporting to other formats; exporting Thinking; exporting several chats at once; deleting uploads; a line under the answer saying how many pictures were sent; removing hidden details from pictures (a camera's place and device data are kept and sent as uploaded; the README says so); more than about 15 very large picture calls at the same moment; watching or freeing the files volume (pictures and Slides files share 20 Gi and nothing is deleted: when it is full, uploads answer `storage_unavailable` and Slides jobs fail; the README says how to see the free space with `kubectl exec` and `df`, and that what to do then is Aziz's decision); Helm.

## 14. Changes agreed during the build — these override the sections above

| Row | Time | Change | Why | Who |
|---|---|---|---|---|
| 1 | 17 Nov 10:35 | No change to the base: Aziz approved the merge of this spec into `main` ("Yes. The merge was approved."), so the base is `main` right after the merge (`605fcf2`), tagged `stage-5-base`, as the header says. An earlier wording of this row, merged by mistake, said the base was the spec branch | The yes came in two messages a minute apart | Aziz; corrected by Claude |
| 2 | 17 Nov 10:34 | The three builders run Codex with full access | "Just do it full access, make it happen fast, parallelize" | Aziz |
| 3 | 17 Nov 10:45 | Section 9: one run uses three of the check user's 20 daily pictures, so after six runs 18 are used and a seventh run meets the limit on its third upload, not at item 2. The script prints the daily-limit FAIL line at whichever upload gets 429 `upload_limit`, stops the remaining items, restores what it changed and exits non-zero | Codex C stopped and asked: the arithmetic in section 9 was wrong | Claude, as spec author, on Codex C's question |

## 15. Decisions from the spec review (binding; override anything above that disagrees)

Review 1, Claude Code (Opus 5.5), 17 Nov 2026 10:04, 24 findings (4 blocking, 14 should fix, 6 notes); the full text is `stage-5-spec-review-1.md` in the course folder's `reviews/`. Decisions by Claude as spec author; the sections above already carry them.

| No | Finding, in short | Decision |
|---|---|---|
| 1 | The shared examples index and the contracts README still describe the old upload; no Part could change them | ACCEPTED: Part B owns the upload entries of `contracts/examples/index.json` and the upload paragraph of `contracts/README.md` (sections 7, 11) |
| 2 | "Claude allows 5 MB per picture and 32 MB per request; OpenAI 50 MB" | REJECTED on the facts: the reviewer wrote from memory (it said so). The providers' pages read on 17 Nov say 10 MB encoded and 128 MB (Claude), 512 MB (OpenAI). ACCEPTED: the dated links are now in section 4, and section 2 item 4 (h) tries the largest request on every tier |
| 3 | "DeepSeek's API takes text only" | REJECTED on the facts: DeepSeek's vision guide read on 17 Nov shows `deepseek-flash` with pictures. ACCEPTED: link and model IDs in section 3 item 5; still unverified with our keys (section 12) |
| 4 | The 7 MiB test was promised in the pre-mortem but not in Done when | ACCEPTED: section 2 item 4 (h) |
| 5 | The check prints only PASS or FAIL; Aziz asked that everything be shown | DECIDED by Aziz, 17 Nov 10:11 ("let's keep it simple"; "PASS/FAIL is enough for the check script"): `87` prints one PASS or FAIL line per item, each line naming what it checked, as `77` and `78` do. The script runs in the Shell tile where the class watches |
| 6 | The error code after failover was undefined | ACCEPTED: section 4 "Provider says no" |
| 7 | One corrupt picture would block a conversation | ACCEPTED: a picture is in view only if its answer completed (section 4 "Pictures in view") |
| 8 | The message being sent was not covered by the history rule | ACCEPTED: sections 4 and 6.2 |
| 9 | Order of the upload checks; two sends at once would give 503 | ACCEPTED: section 6.2 |
| 10 | When the preview clears; a failed send | ACCEPTED: section 6.4 and section 12 |
| 11 | The person's own text would be reformatted as Markdown in the export | ACCEPTED: user text is written as typed (section 6.2) |
| 12 | The limit was a setting in one place and fixed in three | ACCEPTED: the message comes from the setting; the setting may only be lowered; the MB rule is fixed (section 4) |
| 13 | The log search could not run inside a check pod, and searched the picture's header | ACCEPTED: section 9 items 6 and 8 run on harness; a slice from the middle |
| 14 | The tile list contradicted the global rules | ACCEPTED: Aziz's words cited in section 0; the global rules sentence updated in this pull request |
| 15 | File name handling left the builder guessing | ACCEPTED: section 6.2 |
| 16 | Export audit failure and the status of `image_refused` undefined | ACCEPTED: section 6.2 |
| 17 | Phone photos carry hidden place data that is kept and sent | ACCEPTED as a stated limit (sections 4, 13; README). Aziz, 17 Nov 10:11: "Since this is for internal use, it's all right for the phone and location data to be there." |
| 18 | No memory figure for several people at once | ACCEPTED: 2Gi and the sizing in section 4; the rest is a known limit |
| 19 | The ownership worry is mostly settled | ACCEPTED: reason updated (section 4) |
| 20 | No Part could prove the time zone in the built image | ACCEPTED: `87` item 6 proves it in the running pod |
| 21 | The removal guard is a trigger, not a role | ACCEPTED: section 5 |
| 22 | Download headers and the missing-file status | ACCEPTED: section 6.2 |
| 23 | "Date" against export time; no zone shown | ACCEPTED: sections 1 and 6.2 |
| 24 | Confirm versions; tables need switching on; strikethrough | ACCEPTED: versions were read from PyPI on 17 Nov (`pip index versions`); `table` and `strikethrough` are switched on (section 4). The Harness lock file need not match the Slides worker's (separate packages) |

Review 2, Claude Code (Opus 5.5, fresh session), 17 Nov 2026 10:24, 11 findings (none blocking, 5 should fix, 6 notes); `stage-5-spec-review-2.md`. All accepted.

| No | Finding, in short | Decision |
|---|---|---|
| 1 | "The server has stored the message" was wrong for most refusals; the question on screen after a refusal was undefined | ACCEPTED: section 6.4 names the codes for "stored" and "not stored" and what the screen does for each |
| 2 | The "pictures in view" rule could not be built without guessing | ACCEPTED: section 4 defines the answer, the candidates and the order |
| 3 | The global rules' tile sentence contradicted itself | ACCEPTED: rewritten in the global rules |
| 4 | "Lower only" was not enforced and broke below 1 MiB | ACCEPTED: a whole number of MiB from 1 to 7, or the Harness does not start |
| 5 | Searching the Word file's raw XML could fail falsely | ACCEPTED: the check joins the text of each paragraph first |
| 6 | The follow-up check could not fail (the first answer already said the colour) | ACCEPTED: a two-colour picture; the follow-up asks for the half the first answer never named |
| 7 | The order of the upload checks was not fixed | ACCEPTED: fixed in section 6.2; the oversized test body starts with the PNG signature |
| 8 | Word would number a second list 4, 5, 6 | ACCEPTED: numbers are written as text from the Markdown |
| 9 | Audit rows arrive a little later | ACCEPTED: the check waits up to 60 seconds |
| 10 | Two wording slips in the required tests | ACCEPTED: corrected and listed by name |
| 11 | The daily limit does not protect the disk | ACCEPTED: lowered to 20 a day, and stated as a known limit with what happens when the volume is full |

Review 3, Claude Code (Opus 5.5, fresh session), 17 Nov 2026 10:30, narrow round on the 11 fixes of round 2: eight in place with nothing new; 4 findings from the other three (1 should fix, 3 notes); `stage-5-spec-review-3.md`. All accepted.

| No | Finding, in short | Decision |
|---|---|---|
| 1 | With 20 pictures a day, the check could run only five times a day | ACCEPTED: tier 1 reuses the first upload, so six runs fit; the seventh says why it fails (section 9) |
| 2 | Two "not stored" codes could also come after the question was stored | ACCEPTED: that one case answers `unavailable` (section 6.2) |
| 3 | A pre-mortem row contradicted section 6.4 for `upload_used` | ACCEPTED: row corrected |
| 4 | "The first answer never said blue" was assumed, not checked | ACCEPTED: item 3 now checks it |
