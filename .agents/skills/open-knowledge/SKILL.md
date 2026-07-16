---
name: open-knowledge
description: "MUST invoke before reading or editing any `.md` / `.mdx` file, and before any `mcp__open-knowledge__*` tool call (`exec`, `search`, `write`, `edit`, and the rest). This skill is installed into the repository by `ok init`, so its presence alone means this is an OpenKnowledge project — its runtime contract governs every markdown file here, with no need to probe for a `.ok/` directory. Authoritative agent-runtime contract for working inside this OpenKnowledge project."
compatibility: "Claude Code, Claude Desktop, Claude Cowork, Claude.ai web. Requires OpenKnowledge MCP server + code execution."
metadata:
  version: "0.19.2"
  author: "Inkeep"
  repository: "https://github.com/inkeep/open-knowledge"
---
# OpenKnowledge — agent guidance

OpenKnowledge (OK) is a markdown-CRDT collaboration platform exposed via MCP. This skill carries the behavioral rules agents need to use it fluently. Every section is a MUST unless marked otherwise.

> **Authoritative source.** This skill is the single source of OpenKnowledge agent guidance — the full attach rule, grounding rule, media rules, dead-link verification, and failure-mode guidance live only here.

> Skill version: tracks `@inkeep/open-knowledge-server` package version. Check `cat ~/.ok/skill-state.yml` to see what's installed locally. **Version floor:** `ok seed` (referenced below) requires `@inkeep/open-knowledge` >= 0.4.0. If `ok seed` errors with `unknown command`, upgrade: `npm install -g @inkeep/open-knowledge`.

## TL;DR — the 90% case

1. **Reads:** `exec("cat …")` for a single doc, `exec("ls -A …")` for a directory (with folder defaults + template menu), `exec("grep …")` for literal, `search` for ranked retrieval. Native `Read` / `Grep` only on source code (`.ts` / `.py` / …), never on in-scope `.md` / `.mdx`.
2. **Writes:** `write({ document: { path, content } })` for a new or full-replace doc; `edit({ document: { path, find, replace } })` for a body find/replace; `edit({ document: { path, frontmatter } })` for a frontmatter merge-patch (`null` deletes a key). `delete({ document })` removes, `move({ from, to })` moves/renames. Body find/replace is body-only — frontmatter goes through the `frontmatter` patch. Pass a one-line `summary` (≤80 chars, user-facing outcome) on every content write — it's the timeline change-note (see §Writing).
3. **Preview:** every OK read/write response carries a route-only `previewUrl` (`/#/<doc>`, no host:port). If you have a `preview_*` tool, call `preview_start("open-knowledge-ui")`; if you have an in-app browser, call `preview_url` once for the full browser URL and navigate to it; on the Claude Code CLI (no browser tool), run `ok open <doc>` to open it in the OK Desktop app. Surface to the user on a `start-ui` warning (no UI running). Don't `preview_screenshot` to confirm edits — the CRDT tool response is the confirmation.
4. **Workflow guides** — `workflow({ kind: 'ingest' | 'research' | 'consolidate' | 'discover' })` returns a procedural guide, not data. Use it when the work fits the layer; follow the numbered steps.
5. **Direct questions:** a plain business question ("which customers…", "can we use…", "what did we decide about…") routes to `search` / `exec` + a cited answer — no "research" or "report" keyword needed. Persist the answer as a page only when it is durable, spans multiple docs, and isn't already covered — *offer* first, never auto-create. See §Answering direct questions from the corpus.

Everything below is depth. Read on demand.

## Tool index — 17 tools

The full MCP surface, grouped by risk-level. Every tool's `kind` / `action` set is single-risk-level (never a read and a write behind one discriminator).

- **Reads** — `exec` (primary; shell-style `cat`/`ls`/`grep`/`find` with frontmatter + backlink + history enrichment), `search` (ranked, BM25 + recency), `history` (versions for a doc), `links` (`kind: 'backlinks'|'forward'|'dead'|'orphans'|'hubs'|'suggest'`, or an array of those for a one-call audit, e.g. `links({ kind: ["dead", "orphans", "hubs"] })`), `config` (resolved config), `palette` (markdown-native authoring forms + themed `html preview` embed starters + theme tokens; pass `components` for the canonical component JSX schemas), `preview_url` (browser-reachable preview URL on demand), `share_link` (GitHub-substrate share URL for a doc or folder; read-only against `.git/`, no commits/pushes — returns a clear error when the project has no GitHub remote, since agents do not publish projects).
- **Writes** — four native CRUD verbs, polymorphic over `document` / `folder` / `template` / `asset` (Pattern B: per-target fields nested inside the address key; pass EXACTLY ONE target):
  - `write` — create/overwrite a `document` (supports `document.template` instantiation), create a `folder` (with open-shape frontmatter), create a `template`, or upload an `asset`.
  - `edit` — modify a `document` (body find/replace OR frontmatter merge-patch), a `folder` (frontmatter merge-patch), or a `template`. (No asset — binary has no text body.)
  - `delete` — remove a `document` (name or array), `folder`, `template`, or `asset`.
  - `move` — move/rename a `document`, `folder`, or `asset`; rewrites referrers.
  The OUTPUT mirrors the input: `write`/`edit`/`delete` nest their result under the same target key you passed (`{ document: {…} }` / `{ folder: {…} }` / `{ template: {…} }` / `{ asset: {…} }`, or `{ documents: [...] }` for a batch). The preview envelope (`previewUrl`, `warning`, `previousPreviewUrl`) stays at the top level — same for every tool.
  Plus `checkpoint` (save a named version) and `restore_version` (roll a doc back to a prior version). A folder's own frontmatter is open-shape exactly like a doc's (self-only, does NOT cascade into child docs); templates are what new docs in a folder start with.
  **Self-correcting on misuse:** the few constraints JSON Schema can't express — "pass exactly one target", "`find` needs a `replace`", body-XOR-frontmatter — are enforced by a *teaching error*: a wrong call returns `isError: true` with a one-line message naming the exact corrective shape. Read it and retry with that shape; don't guess.
- **GitHub-sync conflicts** — `conflicts` (`kind: 'list'` to enumerate, `kind: 'content'` for base/ours/theirs stages + lifecycle), `resolve_conflict` (write a chosen resolution + commit; destructive). Mutating writes against a doc in conflict return RFC 9457 `urn:ok:error:doc-in-conflict` (409); `exec("cat …")` returns `lifecycle: {status, reason} | null` so you can detect the state proactively. See *Conflict-aware writes*.
- **Workflow** — `workflow` (`kind: 'ingest' | 'research' | 'consolidate' | 'discover'`; returns procedural guides, not data).

Tools NOT in OK MCP (they belong to your agent host): `preview_start`, `preview_screenshot`, `WebFetch`, `WebSearch`, native `Read` / `Grep` / `Glob` / `Edit`. The STOP rule below governs which of those you may use on in-scope markdown.

## STOP — native tools on in-scope `.md` / `.mdx`

When this workspace has OpenKnowledge MCP configured, do **not** use your host's native file tools on markdown paths inside the content directory. The ban covers every common rationalization:

- **Native `Read` / `Grep` / `Glob` on in-scope `.md` / `.mdx`** — the original case.
- **`Bash ls` / `Bash find` / `Bash cat` on dirs containing in-scope markdown** — use `exec("ls -A …")` / `exec("find … -name '*.md'")` / `exec("cat …")` instead. Native returns bare names; `exec` returns frontmatter, backlink counts, and recent activity per child. `-A` shows hidden entries (`.ok/`, `.okignore`) which OK projects carry; omit `.` and `..` rows that `-a` would add.
- **Glob patterns that target markdown** (`**/*.md`, any dir known to be markdown-heavy like `specs/**`, `reports/**`, `docs/**`) — use `exec` with `find`, or `exec("ls -A <dir>")`.
- **Dispatching the Explore / general-purpose subagent for markdown-heavy exploration** — subagents use native `Read` / `Grep` / `Glob` internally and bypass OpenKnowledge entirely. Do markdown exploration yourself via `exec` / `search`. Subagents remain appropriate for **source-code** exploration.
- **Native `Read` / `Grep` on any in-scope markdown inside `.ok/`** — the `.ok/` directory is in-scope; if it carries `.md` / `.mdx`, treat those the same as any other knowledge-base file.

Why: native tools skip frontmatter, backlinks, shadow-repo activity, and project git history that OK's tools return for every matched knowledge-base file. `exec` is the primary read surface; it runs read-only bash (`cat`, `ls`, `grep`, `find`, `head`, `tail`, `wc`, `sort`, `uniq`, `cut`) and returns raw stdout plus enriched metadata per file. One command or a pipe (`|`) per call — it is NOT a shell, so `&&` / `;` / redirects are rejected; list several dirs with `ls -A a b c` or make separate calls.

**MCP tool visibility — not seeing `exec` is NOT the escape hatch.** MCP wiring varies by client. Claude Code, Cursor, Codex, Windsurf, VS Code — each surfaces MCP differently. Server labels are user-defined; tools may not appear as top-level symbols named `exec` in your specific UI. If OpenKnowledge is registered as an MCP server in this workspace, route markdown reads through its `exec` / `search` via your client's documented MCP invocation (including any generic "call MCP tool" flow). Registration is the test, not top-level-symbol visibility.

**Escape hatch.** Native `Read` / `Grep` / `Glob` on `.md` / `.mdx` is allowed **only** when no OpenKnowledge MCP server is registered for this project, **or** immediately after you tried an MCP call and it failed — then begin a user-visible sentence with `OpenKnowledge MCP unavailable:`. Never use the hatch because you skipped your client's MCP path, didn't see `exec` as a top-level tool, or rationalized the skill wasn't necessary.

**Source code and non-markdown files** (`.ts`, `.py`, `package.json`, …): native `Read` / `Grep` / `Glob` always.

## Reads — examples

- Read a file: `exec("cat <path>.md")` — contents + full rich enrichment.
- List a directory: `exec("ls -A <dir>")` — per-child frontmatter, recursive markdown counts, most-recently-updated doc per subdir, the folder's own `title`/`description`/`tags` + `templates_available`. Prefer `-A` over plain `ls` to surface dot-prefixed entries (`.ok/`, `.okignore`) without the noisy `.`/`..` rows that `-a` adds.
- Literal search: `exec("grep -rn <term> <dir> | head -5")` — matches + enrichment on matched files.
- Ranked search: `search({ query })` — cmd-K parity (title boost + body BM25 + recency); use when picking the best doc, not when listing every occurrence.

## Answering direct questions from the corpus

A direct question you can answer from existing documents — "which customers have non-standard indemnity?", "can we use Alloy's logo?", "what did we decide about X?" — does **not** need the words "research" or "report" to route here. Retrieve with `search` / `exec`, read the relevant docs, and **answer in chat with inline citations to the source docs you used**. That is the complete, correct default — most questions end here. This is NOT `workflow({ kind: 'research' })`: research gathers and synthesizes *external* sources behind a scoping gate; a corpus question just reads what the knowledge base already holds. (Inside an active `workflow({ kind: 'research' })` session, research's own "file valuable Q&A back" step governs how answers are persisted — not this section.)

**Offer to persist the answer only when it is durable knowledge the KB is currently missing** — when ALL of these hold:

- it **synthesizes across multiple docs** or surfaces a non-obvious fact a reader couldn't get from a single doc in one read — two docs that independently state the *same* fact are NOT synthesis; synthesis means combining information no single source holds in isolation;
- it's **reusable** — likely to be asked again, or it records a decision / reference others will need;
- **no existing doc already answers it** — scan first (`search`, `exec("grep …")`); if one does, point the user to it instead of writing a near-duplicate;
- the answer is **sourced** per §Grounding, not speculation.

When all hold, *offer* — don't write yet: "This pulls together [N docs] — want me to save it as `<slug>.md` under `<folder>` so it's findable next time?" On a yes, `write` it with frontmatter + inline citations to the source docs (§Grounding, §Linking). **Never auto-create the page.** A single-doc lookup, a navigational question, or anything you'd hesitate to call durable does NOT warrant an offer — answer in chat and stop; don't even prompt to save it. When in doubt, stay in chat: a missing page costs one re-query; a junk page pollutes the corpus permanently.

**Headless / no user to ask** (autonomous run): still produce the answer — surface it with inline citations in the tool / run output as you would in chat, so the run log is the record. Default to NOT persisting unless the four criteria are unambiguously met; never persist on a maybe.

## Preview — open the browser at session start

The user watches your edits land in a live browser preview. Open it once at session start, then keep working. Re-navigate only when the user asks to open a different doc, or to land them on a finished deliverable (see below) — not to re-check your own edits.

**End a turn on the deliverable, not your scratch space.** Keep the preview steady *during* a multi-doc task — don't yank it around to re-check your own edits. But when a turn created or substantially changed user-facing docs, navigate the preview to the primary deliverable before you hand back: the hub / overview / index page when you created several docs, or the changed doc when you changed one. Don't step the user through every supporting source card — the user is watching, so leave them on the result.

**`previewUrl` is a route, not a URL to open.** Every read response (per-doc, on `exec` / `search` / `links` rows) and every write response carries a `previewUrl` — a route fragment like `/#/specs/foo/SPEC`, with **no scheme, host, or port**. It identifies *which doc* to preview, not a URL to hand a browser by itself. Never construct or guess preview URLs.

**OK ships first-class preview support for three apps — Claude Code Desktop, Cursor, and the Codex desktop app — plus the Claude Code CLI on a separate track (below). Make the preview seamless in each.** Match on the tool you actually have (capability, not host name): if a tool can navigate to a URL, it counts as an in-app browser. The three apps map to:

- **Claude Code Desktop — you have `preview_*` tools** (e.g. `preview_start` + `preview_eval`) → **First open of the session:** to land directly on a doc, arm it first with `preview_url({ armPaneTarget: true, document })` (or `folder`), then `preview_start("open-knowledge-ui")` — `ok ui` redirects the base-open straight to the armed route, so the pane opens on the doc, not root. Plain `preview_start` (no arm) opens at root. **Moving between docs once the pane is open: do it in one `preview_eval` step — set `window.location.hash` to the target's route fragment from the response `previewUrl`, the part from `#` on (e.g. `window.location.hash = '#/specs/foo/SPEC'`).** That drives the SPA router directly. Arm + `preview_start` only redirects a *fresh* open; it can't move an already-open pane (`preview_start` reuses the live process without reloading), so use `preview_eval` there. Don't read or edit `.claude/launch.json` — host-managed; the OK lock-collision proxy handles the UI-already-running case. If `preview_start` fails, report it; don't "fix" `launch.json`.
- **Cursor / Codex desktop — no `preview_*` tool, but you have an in-app / built-in browser tool** → call `preview_url` once for the **exact** target (`document` for a doc, `folder` for a folder) and navigate your **in-app browser** straight to the returned `url`. Open that deep URL directly — never the root then navigate; omit both args only for the root. Drive the tool your host gives you:
  - **Cursor** → its built-in **Browser** tool, the **`Navigate`** action (`browser_navigate`, via Cursor's own `cursor-ide-browser`). Navigate it to the `url` yourself — don't print the URL or shell out to the system browser. (A *surfaced* link in Cursor follows its "Browser Tab" vs "Google Chrome" picker and may open the system browser; you calling `Navigate` avoids that. A third-party MCP like OK cannot push a URL into the pane — only the agent's own `Navigate` can.)
  - **Codex desktop app** → its in-app **Browser** plugin (`@Browser`); drive it to the `url` (Codex navigates via `tab.goto`).
  - **Any other host** with a URL-navigation tool (`browser`, `view_url`, `open_url`, `web.browse`, …) → navigate it to the `url`. **This is also the fallback when a named tool above isn't present under that exact name** (hosts rename tools): match on the capability, not the name. If no URL-navigation tool exists at all, drop to the Claude Code CLI track below.
- **Honor `autoOpen`** (on `preview_url`, or on `warning` for write tools). If `false`, do not open or refresh any preview UI; surface the URL only if asked.

**Claude Code CLI — a separate track (no browser).** The CLI is pure stdio: don't open or fake a browser. For an "open `<doc>`/`<folder>`" request, run **`ok open <doc>`** (`--folder` for a folder) — it deep-links the doc into OK Desktop (folders open in the browser); an action you run, not a URL to print. Any other pure-stdio host with **no** URL-navigation tool is on this track too — but if you *do* have a tool that navigates to a URL, use the in-app branch above, not this track. The Codex **CLI**, **IDE extension**, and **Cloud** also live here (web search only, no localhost browser). No `ok` on PATH or no shell → `preview_url`, then `open <url>` in the system browser as a last resort, and say so plainly. The system browser is the fallback, never the default.

**Opening or reading a file IS a preview navigation.** On any "open `<file>`" / "read `<file>`" request, navigate the browser to that doc's `previewUrl` route from the tool response — not a separate fetch, not a fresh system-browser launch.

**Four signals to check if the preview is already attached** (read these from each write response):

1. You opened/navigated earlier this session → don't reopen.
2. Write response has `previewUrl` (non-null route) and NO `warning` → a browser is attached somewhere; do nothing.
3. `warning: { action: "attach-preview-once", previewUrl, message }` → UI reachable, no browser attached; navigate one-shot (`preview_start`, or `preview_url` → in-app browser).
4. `warning: { action: "start-ui", previewUrl: null, message }` → no UI running anywhere. Surface the message verbatim — recovery options are in the in-band copy. Don't loop on retries.

Warnings fire at most once per session in the fresh-start case.

**Re-point at the end of a multi-doc workflow; don't claim a doc is on screen unless you put it there.** The one-shot attach (signal 3) opens the preview *once* — later writes do NOT move the pane; it stays on the doc you last navigated to. When a turn touches several docs, finish by navigating the preview to the doc the user should land on, using your host's move mechanism (`preview_eval` setting `window.location.hash` from the response `previewUrl`, or `preview_url` → in-app browser; honor `autoOpen`). Until you have navigated there *this* turn, don't tell the user a doc is "open" / "on screen" — at most, say the preview may still be on the doc you opened earlier.

**`previewUrl: null` only means "no UI reachable" on the two attach-warning tools: `write` / `edit`.** Workflow tools return prose and don't carry `previewUrl`. `delete` / `move` emit `previousPreviewUrl` (different field, for closing stale tabs) and don't fire attach warnings. `preview_url` auto-starts the backend on demand (same `OK_MCP_AUTOSTART` gate as writes; a cold first call can take seconds) and reports `running: false` + `url: null` only when no UI could be reached — its hint names the right command.

If you see `"Hocuspocus server is not running"`, run `ok start` and retry.

OK Electron and `ok ui` share `ui.lock`; when a second UI binds a different port, the OK lock-collision proxy bridges it to the live server transparently. That is exactly why `previewUrl` is route-only — the port behind the proxy is not the agent's to use. **Do not nudge the user to quit OK Electron to free a port** — the proxy handles it, and quitting tears down a UI in active use.

**The preview is read-only for the agent — it is the user's view, not a surface you read back.** You cannot click or type to drive edits — the CRDT flow is one-way (agent → MCP → CRDT → preview).

**No screenshots to confirm edits, no generic verification loop.** Do NOT take `preview_screenshot` (host tool, not OK MCP) after a write, and do not run a generic snapshot/eval/screenshot verification loop — OK's preview is a read-only, one-way mirror, so the CRDT tool response *is* the confirmation that an edit landed. Screenshot only when debugging a visual rendering issue or when the user explicitly asks to see the preview — never to confirm an edit landed. (Navigating the pane with `preview_eval` by setting `window.location.hash` is fine — that drives the view, it is not a read-back verification loop.)

## Writing

Call `write` / `edit` as soon as you have content. Native `Edit` / `sed` / direct `Write` on in-scope markdown is forbidden — it bypasses the CRDT and loses agent attribution in the shadow repo.

**Persist incrementally — the knowledge base IS your checkpoint (MUST).** On any multi-step or long-running task — a research sweep, a multi-source synthesis, a batch of docs — write completed work to the KB as you finish each unit: per section, per source, per doc. Never hold finished findings only in your context waiting for one final write at the end. A rate limit, crash, or context compaction mid-task discards everything still unwritten; work already persisted to a doc survives, and you resume by reading the doc back instead of redoing the work. Create the target doc early (skeleton + frontmatter), then `edit` each section in as it firms up. Completed, paid-for work that existed only in context and got dropped on a rate limit is the exact failure this rule prevents — the KB is where work goes to be safe, not a thing you save to once at the finish line.

**Pass a `summary` on every content write (SHOULD).** `write`, `edit`, and `move` each take a one-line `summary` (≤80 chars) describing the user-facing outcome of the change — "Add gear list and permit info", not "edited trip doc". It renders as a bullet under your name in the document timeline and is the only human-readable change-note persisted to the shadow-repo history; omit it and the timeline shows *that* you wrote but not *what changed*. Write it from the reader's perspective, keep it specific, and avoid secrets or PII (it lands in git history). Each entry in the batch `documents:` form carries its own `summary`.

**Reach for visual structure where it aids comprehension.** Default to the right OK primitive over flat prose: a Callout (`> [!NOTE]`) for a key caveat, a ` ```mermaid ` diagram for a process or relationship, a table for options or comparisons, an `html preview` chart for numbers. **Call the `palette` MCP tool as you draft** (and `palette({ components })` for a canonical's JSX schema) — it returns copy-ready markdown-native forms, themed `html preview` embed starters, and the theme tokens, so the visual lands themed and in the content graph instead of hand-rolled. Don't decorate — use a visual only when it carries the point better than prose would. Full catalog: §Components.

**Advisory warnings on writes.** `write` and `edit` responses may include `structuredContent.document.warnings` (batch: per-doc `structuredContent.documents[].warnings`) — advisory entries discriminated by `kind`, each also summarized as a `⚠` line in the response text. The write always landed; the entries tell you what to do next. Write-integrity kinds mean re-read the doc (`exec("cat <path>")`) before continuing: `content-divergence` (`{ kind, intendedBytes, actualBytes, byteDelta, hint }` — the converged Y.Text doesn't match what the payload composed to: concurrent peer residue, or — rare — a primitive regression) and `disk-edit-reconciled` (an out-of-band disk edit was folded in before your write landed on top). The renderability kind `mermaid-parse-error` (`{ kind, fenceIndex, fenceFirstLine, message, line? }`) means that mermaid fence will not render — fix the fence and re-edit. (A deprecated single-valued `warning` field on the HTTP body mirrors the highest-precedence integrity entry for older consumers.) Distinct from the preview-attach `warning` field (`action: "attach-preview-once" | "start-ui"`), which stays at the top level — separate keys, can coexist.

To author an MDX doc (the KB renders MDX/JSX components), set `extension: ".mdx"` on the create: `write({ document: { path: "guides/widget", content, extension: ".mdx", position: "replace" } })` lands `guides/widget.mdx`. A `.mdx` suffix typed into `path` works too (the `extension` field wins if you pass both); omit both and it lands `.md`. An existing doc keeps its on-disk extension regardless — changing it in place isn't available via the MCP today.

To delete a doc, call `delete({ document })` — never `rm` / `unlink` / native `Bash` removal on in-scope markdown. The MCP path closes open agent sessions and unloads the doc from Hocuspocus before unlinking; native `rm` desynchronizes those. Deletion is irreversible — call `checkpoint()` first if you may need to roll back (it snapshots the whole project; afterwards restore the doc via `restore_version({ document, version })`, finding the `version` in `history`), and `links({ kind: "backlinks", document })` first if you want to fix referrers that will become redlinks. To move or rename a doc instead of delete + rewrite, use `move({ from, to })` — it auto-detects document vs folder vs asset and rewrites incoming references atomically.

**If `edit` returns "Text not found" on text you can verify exists on disk** (via `exec("cat …")`), the MCP session is likely stale (e.g., after a folder rename or server restart). Treat this as the escape-hatch trigger from the STOP block: prefix your next user-visible sentence with `OpenKnowledge MCP unavailable:` and report the inconsistency. Don't loop on retries — the symptom is structural, not transient.

## Conflict-aware writes

Projects with GitHub sync enabled may carry docs in a merge-conflict state. The MCP server refuses every mutating call against such a doc with a structured RFC 9457 response:

```json
{
  "type": "urn:ok:error:doc-in-conflict",
  "title": "Document is in conflict.",
  "status": 409,
  "detail": "The document is in a merge-conflict state. Call conflicts({ kind: 'content' }) + resolve_conflict before retrying.",
  "file": "notes/sso.md",
  "resolutionOptions": ["mine", "theirs", "content", "delete"]
}
```

The gate covers `write`, `edit`, `delete`, `move`, `restore_version`, and agent undo (the doc-CRDT write spine; template/folder ops are fs-direct). You cannot route around it by writing content that byte-matches one of the merge stages — the gate refuses on lifecycle state, not on body equality.

**Detect proactively.** `exec("cat <path>.md")` always returns `lifecycle: {status, reason} | null` alongside the body. When `status === 'conflict'`, switch to the resolution flow before attempting any mutation.

**Resolution flow.** Three tools compose:

1. `conflicts({ kind: 'list' })` → enumerate every doc currently tracked in conflict.
2. `conflicts({ kind: 'content', file })` → returns `{ content: { base, ours, theirs, shape, lifecycleStatus } }` (the result nests under the `content` kind key). `ours` reflects the live Y.Text (what the human user sees in the editor) when the doc is loaded server-side and is marker-free; falls back to `git show :2:<file>` otherwise (e.g. after an editor reopen seeded markers into Y.Text).
3. `resolve_conflict({ file, strategy, content? })` → write the chosen bytes and commit. Strategies: `mine` runs `git checkout --ours` (your committed stage 2), `theirs` runs `git checkout --theirs` (their stage 3), `content` writes the bytes you supply, `delete` runs `git rm` (for delete-modify / modify-delete shapes where a stage is missing).

`file` is a `.md` / `.mdx` path relative to the project dir (extension included) — mirrors the on-disk shape, not the extension-less `document` path used by other tools.

The resolve operation is best-effort and NOT atomic: `git checkout --ours/--theirs && git add` may succeed but the subsequent `git commit --no-edit` can fail (pre-commit hook rejection, locked index). On commit failure the staged files are re-`git add`-ed back into the unmerged index and the tracked entry remains in `conflicts.json` — re-call `resolve_conflict` after the user clears the blocker.

## Components — write the markdown-native form, not JSX

OK auto-promotes markdown-native syntax into themed canonical components at parse time. **Write the markdown-native form — don't reach for JSX when one exists.** The promoted component is themed, accessible, and part of the content graph; hand-rolled JSX is none of those, and it fights the model's markdown prior instead of using it.

| Want | Write this (markdown-native) | Promotes to |
| --- | --- | --- |
| Callout / admonition | `> [!NOTE]` + body — 15 types (NOTE, TIP, IMPORTANT, WARNING, CAUTION, …); append `+` / `-` (`> [!NOTE]+`) to make it foldable | themed Callout |
| Collapsible section | `<details><summary>Title</summary>` … `</details>` | themed Accordion |
| Diagram | a ` ```mermaid ` fenced block (flowchart, sequence, class, state, ER, gantt, pie) — label-text pitfalls + escapes: `palette({ components: ["Mermaid"] })`; parse failures come back as `warnings` entries on write/edit | Mermaid diagram |
| Math | `$x$` inline, `$$…$$` block | KaTeX Math |
| Inline a doc or asset | `![[file]]` | wiki embed |

`Tabs` is the lone canonical with **no** markdown-native form — write the JSX directly (`<Tabs><Tab label="…">…</Tab></Tabs>`). For any canonical's full JSX prop schema, call `palette({ components: [ids] })`. If no canonical fits, any `<TagName>…</TagName>` falls through as raw MDX — but prefer a canonical when one matches.

**Discover the palette in one call.** `palette` returns every markdown-native form (copy-ready `example` + `guidance`), the themed `html preview` embed starters, and the injected theme-token list — the source of truth for component-forward, themed authoring. Canonical names/counts beyond the markdown-native set are project-specific; the inventory in the `write` / `edit` descriptions and `palette({ components })` are authoritative for those.

**Show findings, don't just tell them.** When a point is quantitative or comparative — a trend over time, a breakdown, a before/after, a ranking, a distribution — present it visually: a chart or stat-card `html preview` embed, a ` ```mermaid ` diagram, a table, or a Callout for the headline takeaway. Prose-only buries the insight. This matters most where the document's job is to make findings legible — **`research` reports and `consolidate` articles especially**, and any write-up meant to present results. A research article with three dense paragraphs of numbers should have been a chart. Reach for `palette` as you draft, not after.

### `html preview` — themed interactive embeds

A ` ```html preview ` fence (also `htm` / `xml`) renders a standalone HTML/CSS/JS page as a live sandboxed iframe — the extend-to-anything primitive for charts, stat cards, custom SVG, calculators, demos. The iframe auto-sizes to its content; pass `h=` / `w=` (e.g. ` ```html preview h=400px `) only to pin a fixed size.

**Start from a starter — don't hand-roll.** `palette` returns `embedPatterns` (chart, stat cards, custom SVG, interactive control), each already wired to the theme tokens. Copy one and fill in your data — that is the only path that cannot render unthemed. Hand-author a fence from scratch only when no starter is close.

**MUST — never hardcode colors in an `html preview` embed.** OK injects its theme tokens into every preview iframe; an embed that hardcodes hex / `rgb()` renders unthemed — a white box on a dark page, clashing with every component around it. This is the single most common embed mistake. Wire every color to a token: `var(--chart-1..5)` for chart series, `var(--foreground)` / `var(--muted-foreground)` for text, `var(--card)` / `var(--background)` for surfaces, plus `var(--border)`, `var(--primary)`, `var(--radius)`. Don't set a `body` background at all unless you specifically mean to — the iframe already carries a themed one.

````
```html preview
<div style="font-family:system-ui;padding:20px;color:var(--foreground)">
  <h3 style="margin:0 0 10px">Themed embed</h3>
  <div style="display:flex;gap:8px">
    <div style="flex:1;height:48px;background:var(--chart-1);border-radius:var(--radius)"></div>
    <div style="flex:1;height:48px;background:var(--chart-2);border-radius:var(--radius)"></div>
    <div style="flex:1;height:48px;background:var(--chart-3);border-radius:var(--radius)"></div>
  </div>
</div>
```
````

Done wrong, that same embed is `body{background:#fff;color:#1a1a1a}` with a `background:#2563eb` bar — a white box with a hardcoded blue, blind to the reader's theme.

**Charts.** A pure-CSS or inline-SVG chart wired to `var(--chart-*)` re-skins on a theme toggle for free — prefer it. A JS charting library (Chart.js, D3) works too, but a themed `body` does NOT theme the colors you pass the library in JS — read the token at runtime instead of hardcoding:

```js
const c1 = getComputedStyle(document.documentElement).getPropertyValue('--chart-1').trim();
// → pass c1 to Chart.js / D3 as the series color
```

**Boundary.** Reach for a canonical (via its markdown-native form) when one matches the semantic need — it is themed and integrated. Reach for ` ```html preview ` for interactive or bespoke content no canonical covers. ` ```<lang> ` fences for other languages are plain syntax-highlighted code, no preview.

**External resources load directly.** The preview iframe has open network access — an embed can load external stylesheets, `fetch` live data, pull map tiles / remote images, use web fonts, or embed third-party iframes over `https:`. A Leaflet map, a live-`fetch` chart, or a Google-Font embed renders with no extra setup. The iframe is a sandboxed null-origin frame, so an embed can reach the network but can never read the knowledge base, cookies, or auth. (`'unsafe-eval'` is not granted — Chart.js / Leaflet / Plotly don't need it; a library that compiles expression strings at runtime won't run.)

## Grounding — every factual claim needs a source (MUST)

Knowledge-base docs are factual artifacts — whether the project is a wiki, an LLM brain, a spec collection, a research log, or anything else markdown-shaped. Every claim must be traceable, and **the source has to live inside the knowledge base**, not float on the public web.

- **The knowledge base is source-of-truth — closed loop.** External sources don't get *cited out* to the live web; they get *pulled in* via `ingest`, then cited locally. A bare `[source](https://...)` URL inside a knowledge-base doc is **not** a finished citation — it's a TODO that says "this source still needs to be ingested." The chain only works if every leaf is a local doc.
- **Every factual claim MUST cite its source at the point of claim.** No unsourced speculation.
- **Web sources for knowledge-base docs** → fetch the page (your host's `WebFetch` / `WebSearch` / equivalent), then `ingest` it as a local doc, then cite the local path: `[source name](./path/to/source.md)`. The local doc carries the original URL in its frontmatter `source_url:`. **Inline `[source](URL)` is a chat affordance, not a knowledge-base one.**
- **Self-fetched counts.** When YOU fetched a URL to ground a claim that's about to land in the knowledge base, that fetch triggers `ingest` exactly like a user share does. Don't downgrade to inline-URL citation because the fetch was agent-initiated — same KB, same closed-loop contract.
- **Internal cross-refs** → standard markdown link to the OK doc that contains the authoritative claim: `[text](./path/to/doc.md)`. The linked doc itself must cite its sources — chains should terminate in preserved local docs. Where ingested sources live is project-specific (an `external-sources/` folder if the project uses Karpathy's layout; wherever the project's existing layout puts raw references otherwise).
- **If you don't have evidence:**
  1. Run a web search and `ingest` the result, OR
  2. Mark inline `(TODO: needs source)` so a human can verify, OR
  3. Don't write the claim. Do NOT fabricate.
- Unsourced speculation looks authoritative but rots into tribal knowledge that can't be audited. The knowledge base loses its value if readers can't trust it.
- If a fact is in the knowledge base, a reader must be able to trace it to its origin via local docs only — no dead-link-on-the-public-web exposure.

## Linking — use standard markdown links

- **Every noun-phrase that names another document should be linked** using standard markdown link syntax: `[text](./relative/path.md)` or `[text](/absolute/from/content-root.md)`.
- **External web sources are NOT inline body links.** Per the Grounding rule above, web URLs live in the `source_url:` frontmatter of an ingested doc under `external-sources/` (or the project's equivalent raw-sources folder); the body cites the local path: `[source name](./external-sources/source-slug.md)`. A raw `[source](https://...)` inline in the body is a TODO, not a citation — see Grounding for the closed-loop contract.
- **Internal cross-refs between OK docs** → `[text](./other-doc.md)` — link liberally to aid navigation.
- **Every link must resolve to a doc that exists.** Never link to a doc that isn't written yet. If you want to reference something that should have its own page but doesn't: create that page in the same pass, or record it as a tracked task (`TaskCreate`, or your host's task tool — if the host has none, tell the user) and leave the mention as plain prose. A broken link is debt, not a to-do marker.
- **Never wrap a link in backticks.** `` `[text](./foo.md)` `` is a bug — the backticks make it render as literal code rather than a link.
- **Never use HTML anchors** (`<a href="...">`). Markdown link syntax only.
- **Verify before walking away.** After writing a doc, call `links({ kind: "dead", sourceDocuments: ["your/doc"] })` to find broken references. Fix or remove every one — a dead link is never acceptable to leave behind. Companion `links` kinds: `backlinks` (incoming), `forward` (outgoing), `orphans` (no incoming), `hubs` (high-incoming), `suggest` (untextualized mentions worth linking).
- **The editor's red-underline visual lies.** Its dead-link detection tolerates slug-fallback (e.g., `foo` may appear resolved because `foo.md` exists at root). `links({ kind: "dead" })` is strict-exact — trust the tool, not the visual.

**Note on wiki-link syntax (`[[Page]]`):** the parser still handles it for legacy content, but it's NO LONGER the recommended default. Write new content with standard markdown links per above. Seed-pack templates (`ok seed --pack <name>`) may still emit `[[Page]]` placeholders inside template body text — those are legacy. When you instantiate a seed-pack template, replace the legacy placeholders with standard markdown links during the `{shape}`-fill pass.

## Media — images and attachments

- **Markdown syntax only:** `![alt text](./path/to/image.png)`. Do NOT emit HTML `<img>` tags — they don't participate in OK's content graph and don't render consistently across Fumadocs / preview surfaces. Paths resolve relative to the doc.
- **Always a doc-relative path — never a server URL.** Reference an asset by its path relative to the doc (`./image.png`, `../assets/foo.png`), never an absolute `http://localhost:<port>/…`, `127.0.0.1`, or other server URL. `preview_url`'s `url` navigates the *preview* — it is NOT an asset path; never paste it (or any `localhost` base) into an `![]()`. An asset already in the tree is the same rule: find its path with `exec("ls -A <dir>")` and write the relative link. (Upload via `write({ asset })` hands you the exact relative `![alt](ref)` to copy.)
- **Save locally, don't hot-link.** Hot-linked external image URLs rot when the source disappears. Fetch (`WebFetch` / `curl`), save to a local path, reference via relative markdown link, cite the source below.
- **Placement model.** Free-form image embeds → co-located alongside the referencing doc (sha256 same-directory dedup). Raw sources via `ingest` → `external-sources/<slug>.<ext>` + `external-sources/<slug>.md` (the wrapper-binary pair). Check via `exec("ls -A")` if the project uses a different convention.
- **Cannot fetch** (no network, paywall) → don't invent a local path. Omit, or mark inline `(TODO: image needs sourcing from <URL>)`.
- **Meaningful alt text required** — describes WHAT the image shows, not what it is. `![]()` / `![image]()` / `![filename.png]()` all fail. OK indexes alt text — it's both accessibility AND searchability.
- **Cite web image sources** below the image (Grounding rule):
  ```markdown
  ![Aang using the Avatar State to defeat Ozai](./assets/images/aang/avatar-state.png)
  *Source: [Avatar Wiki — Aang](https://avatar.fandom.com/wiki/Aang#Avatar_State)*
  ```
  Original diagrams/screenshots may caption `*Original*` or omit. Unattributed web images are equivalent to unsourced factual claims.

## Folders, frontmatter, templates

Every `.md` / `.mdx` file needs YAML frontmatter — `title` + `description` required, `tags` recommended:

```yaml
---
title: Article Title
description: Brief summary
tags: [relevant, tags]
---
```

Two folder mechanisms, both opt-in and nested: **folder frontmatter** in `<folder>/.ok/frontmatter.yml` (the folder's own properties — open-shape like a doc's, with `title` / `description` / `tags` as conventional keys the UI surfaces; describes the folder, self-only, does NOT flow into child docs) and **templates** in `<folder>/.ok/templates/` (the single mechanism for what new docs in a folder start with). **Most folders have NO `.ok/`** — sparse, lazy-create, auto-clean. A folder gets one only when it carries its own frontmatter or a template.

```
content-root/
├── .ok/                        ← project root .ok/ (config.yml, cache)
├── meetings/
│   ├── .ok/
│   │   ├── frontmatter.yml     ← this folder's own title/description/tags
│   │   └── templates/
│   │       └── prep-notes.md   ← what new meeting docs start with
│   └── 2026-05-01.md
└── research/                   ← no .ok/
    └── auth-providers.md
```

A doc's frontmatter is exactly its own on-disk YAML — folder frontmatter never overlays values onto it. Give new docs starting properties with a template, not with folder frontmatter.

### Read the folder before writing (MUST)

Before creating or editing docs in a folder, **always** call `exec("ls -A <folder>")` once. The response carries the folder's own `title`/`description`/`tags` + `templates_available` (the template menu for `write({ document: { template } })`). Skipping this is how agents land docs that violate folder discipline.

Pre-write checklist:

0. **First-contact check.** If the folder has no frontmatter of its own AND `templates_available` is empty AND `exec("ls -A")` shows substantial content elsewhere, the project hasn't been onboarded — STOP and invoke `workflow({ kind: 'discover' })` (Workflow guides below). Skip on subsequent writes once confirmed.
1. **Read the folder's description** — its `title`/`description`/`tags` tell you what the folder is for. (These describe the folder; they are NOT defaults the doc inherits.)
2. **Read `templates_available`** — each entry has `name`, `title`, `description`, `scope` (`local` / `inherited`). If one matches, **prefer it** over free-form markdown (it's the folder's contract — templates carry frontmatter + body structure hand-authored docs routinely miss).
3. **Read recent siblings** — new docs should match the shape of existing ones (filename, frontmatter, body structure).
4. **Confirm content scope** — `content.dir` (`.ok/config.yml`) defines the root. `.gitignore` / `.okignore` (nested at any depth) define exclusions.

**Once per folder per session** — the checklist doesn't repeat unless you (or the user) changed a folder rule or template since.

### When to use a template (MUST when one fits)

Instantiate via `write({ document: { path, template } })`. Inherited templates (`scope: "inherited"`) are equally valid. Skip only when (a) `templates_available` is empty, (b) no entry matches, OR (c) the user asked for free-form. If you skip, briefly note why in chat.

### When to create a template

Templates make folder structure durable. Create them proactively:

- 2+ sibling docs share a skeleton in a folder with no template → extract via `write({ template })`.
- About to write a doc in a folder where no template fits, AND the shape is reusable → save as template the same turn.
- Scaffolding a new folder for a doc category → pair `write({ folder })` (or `edit({ folder })`) with `write({ template })` in the same turn.
- The user describes a recurring doc shape ("we always log meetings with attendees, agenda, action items") → author the template once.

Note new templates in chat ("saved as a template at `meetings/.ok/templates/prep-notes.md` for next time") so the user sees the discipline grew.

**Keep starter content clean (MUST).** A template body is a reusable skeleton, not a meta-prompt: section headings, real frontmatter, and SHORT `{Stub}` placeholders (e.g. `# {Meeting Title}`). Do NOT bake a workflow's verbose `{...}` prompt-paragraphs (the `research` / `consolidate` shape guidance is for filling ONE doc, not for persisting into every new one), do NOT duplicate sections, and do NOT save a half-filled or in-progress doc as a template. Long "how to fill this" guidance belongs in the folder description, not in the body each new doc inherits. After saving, `exec("cat <folder>/.ok/templates/<name>.md")` and eyeball it — a template propagates to every doc made from it, so a garbled one is a recurring defect, not a one-off.

### When recurring per-doc properties emerge (MUST when a pattern emerges)

If you're writing the same frontmatter (tags, status, a title prefix) on multiple siblings, bake those starting values into a **template** (`write({ template })`) — that's the single mechanism for new-doc starting properties. Folder frontmatter does not cascade values into docs.

### Editing a folder's own description

```ts
edit({
  folder: {
    path: "meetings",
    frontmatter: { title: "Meetings", description: "Meeting notes", tags: ["meeting"] },
  },
})
```

`frontmatter` is open-shape — any key about the folder itself, exactly like a doc's frontmatter (`title` / `description` / `tags` are conventional keys the UI surfaces). It's self-only: it describes the folder and does NOT flow into child docs — put per-doc starting values in a template instead. Each call targets a SINGLE folder by its own `path` (no globs). Use `write({ folder })` to create a new folder, `edit({ folder })` to change an existing one (merge-patch). Clear the folder's frontmatter by passing `frontmatter: {}`, or drop one key with `frontmatter: { key: null }` — the file deletes when empty and `.ok/` auto-cleans if no other tenant remains.

### Creating templates

```ts
write({
  template: {
    path: "meetings/prep-notes",
    content: "# {Meeting Title}\n\n**Attendees:** \n**Date:** \n\n## Agenda\n- \n",
    frontmatter: {
      title: "Meeting Prep Notes",          // REQUIRED — TEMPLATE_TITLE_REQUIRED if missing
      description: "Use before a meeting.", // recommended — soft warning if absent
      tags: ["meeting", "prep"],
    },
  },
})
```

**Substitution allowlist:** template bodies MAY use exactly two server-side substitutions — `{{date}}` (today's ISO-8601 date) and `{{user}}` (calling principal display name). Other `{{...}}` tokens are rejected at write time with `TEMPLATE_UNKNOWN_VARIABLE`. Plain `{shape}` placeholders (e.g., `{Meeting Title}`) are LITERAL — agents fill via subsequent `edit` calls. Delete a template via `delete({ template: { path } })` (auto-cleans empty `.ok/templates/` and `.ok/`).

### Creating a doc from a template

```ts
// Inspect the menu (already done in the pre-write checklist).
exec("ls -A meetings/")
// → templates_available: [{ name: "prep-notes", title: "Meeting Prep Notes", scope: "local" }, ...]

// Instantiate. `template` and `content` are mutually exclusive.
write({
  document: {
    path: "meetings/2026-05-02-roadmap-sync",
    template: "prep-notes",
  },
})

// Fill the `{shape}` placeholders via follow-up edit calls.
```

Templates resolve via leaf → root walk-up at the target's parent folder, closest-wins on filename collision. **`template` and `content` are mutually exclusive** — passing both errors with `TEMPLATE_AND_CONTENT_BOTH_SET`. Substitution happens at instantiation time only; templates on disk show the raw `{{date}}` token.

### Editing frontmatter

`edit({ document: { path, find, replace } })` does NOT change frontmatter (body-only; frontmatter-intersecting find/replace returns HTTP 400). For metadata, use `edit({ document: { path, frontmatter: { key: value } } })` — JSON Merge Patch (RFC 7396), `null` deletes, field-level CRDT merge, atomic per-call. For a full rewrite (body + frontmatter together), call `write({ document: { path, content, frontmatter, position: "replace" } })`.

### Binary-source wrappers (`ingest`-produced)

Docs that wrap a co-located binary file under `external-sources/` carry extra frontmatter so the wrapper-binary pair is fully described:

```yaml
---
title: ...
description: ...
source_url: https://example.com/file.pdf
source_path: ./<slug>.<ext>      # relative to this wrapper
media_type: application/pdf
bytes: 1234567
sha256: <64-char hex>            # of the embedded binary
date_fetched: YYYY-MM-DD
preservation: binary             # OR: text-only / text-extracted
supersedes:                      # OPTIONAL — dated-sibling re-ingest
  - <prior-slug>.md
tags: [source, immutable, layer-ingest, binary]
---

![[<slug>.<ext>]]
```

Body is just the wiki-embed. PDFs/opaque attachments render as a click-dispatching File row; `<Pdf src="./<slug>.pdf" />` is the opt-in inline viewer. See `ingest`'s tool body for full re-ingest / size / executable rules.

## Cadence

When you make a multi-step change (batch of new docs, folder restructure), pause between steps to let the browser preview catch up. The CRDT edit streams live; the preview follows your edit cadence. Don't batch 10 writes in a row — interleave the writes so the user watching the browser sees the narrative progress.

This does not conflict with *Persist incrementally* (§Writing): a checkpoint-write per section/source is naturally spaced by the work that produces that unit (read a source → write its findings → read the next), so those writes *are* the interleaved cadence. The anti-pattern is firing many writes back-to-back with no intervening work — not persisting completed work as you go. When in tension, durability wins: never hold finished work back from the KB to smooth cadence.

This is primarily a human-watchability concern — the user watches edits land in the preview; interleaved cadence makes the narrative legible. When the batch is done, navigate the preview to the primary deliverable (see "End a turn on the deliverable" in §Preview).

**Hub docs.** Don't *create* `INDEX.md` / `README.md` hub files solely to catalog children — `exec("ls -A <folder>")` returns the same view live, with per-file frontmatter + backlink counts. But if a hub doc *already exists* from prior work, keep it updated as children change — interleave: write child → update hub → write next child, rather than batching five child edits and a single trailing hub update.

## Log discipline — check for a project log when KB content changes

Some projects keep an append-only project log to make agent activity auditable. **After any turn that creates, edits, or restructures docs in the knowledge base, check for a project log:** look for a `log.md` at the project root (or at the seed `rootDir` if `ok seed --root <dir>` was used). If one exists, follow whatever its frontmatter `description:` and in-file comment say — they carry the project-specific contract (entry shape, cadence, categories). Different projects log differently — some treat the log as a wiki audit trail, others as an LLM-brain history, others as a spec changelog. If no `log.md` exists, no log discipline applies; don't fabricate one.

The skill carries the trigger ("KB content changed this turn — go look"). The file owns the policy.

## Anti-patterns — at a glance

| Task                                            | Don't                                                                              | Do                                                                                |
| ----------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| List a markdown-heavy dir                       | `Bash: ls specs/`                                                                  | `exec("ls -A specs/")`                                                            |
| Find all SPEC.md files                          | `Glob: **/SPEC.md`                                                                 | `exec("find specs -name SPEC.md")`                                                |
| Find the most relevant page for a query         | `Grep: "pattern" *.md` then read three files                                       | `search({ query: "pattern" })` (ranked: title + body BM25 + recency)              |
| Find every literal occurrence of a phrase       | `Grep: "pattern" *.md`                                                             | `exec("grep -rn pattern <dir>")` (literal, grouped by file, with frontmatter)     |
| Read an individual doc                          | `Read: specs/foo/SPEC.md`                                                          | `exec("cat specs/foo/SPEC.md")`                                                   |
| Explore a markdown-heavy dir                    | `Agent(Explore): "..."`                                                            | Do `exec`-based exploration yourself                                              |
| Answer a direct business question from the corpus | answer in chat and move on (it evaporates), OR save every answer as a new doc      | answer with citations; *offer* to persist only when durable + multi-doc + not already covered (§Answering direct questions) |
| Wait for the server to tell you to open preview | Skip the session-start preview open and wait for the `attach-preview-once` hint    | Open the preview browser at session start; the hint is a fallback when you didn't |
| Ignore the attach hint                          | Skip the `warning: { action: "attach-preview-once" }` hint in write-tool responses | Open the preview when the hint fires (`preview_start`, or `preview_url`); otherwise do nothing |
| Make the Claude Code Desktop preview work       | Read / diagnose / edit `.claude/launch.json` (host-managed config)                 | Call `preview_start("open-knowledge-ui")` and nothing else; the OK lock-collision proxy bridges any port mismatch transparently |
| Open a doc in the app from the Claude Code CLI  | Print the `previewUrl` / `openknowledge://` string for the user to click           | Run `ok open <doc>` — it opens the OK Desktop app (folders open in the browser), with browser fallback |
| Reference another doc                           | `` `[text](./page.md)` `` (backticked) or HTML `<a>`                               | `[text](./page.md)` (raw markdown)                                                |
| Embed an image                                  | `<img src="...">` (HTML), a `localhost:<port>` / `preview_url` server URL, or hot-linked external URL | Fetch + save locally + doc-relative `![meaningful alt](./assets/images/path)`     |
| Write a factual claim in a KB doc               | plausible prose without citation, OR inline `[source](https://URL)`                | `ingest` the source first, then cite the local path per Grounding                  |
| Cite a web source you just fetched              | inline `[source](https://...)` because YOU did the fetch (not the user)            | `ingest` it — agent-initiated fetches are not exempt from the closed-loop rule    |
| Finish a turn that changed KB content           | move on without checking for a log                                                 | check for a `log.md` and follow its contract per Log discipline                    |
| Add an image                                    | empty alt `![](./x.png)` or generic alt `![image](./x)`                            | meaningful alt + source caption below                                             |
| Catalog folder contents                         | create `INDEX.md` hub file                                                         | `edit({ folder: { path, frontmatter } })` writes `<folder>/.ok/frontmatter.yml` |
| Write a doc in an unfamiliar folder             | go straight to `write` with hand-authored markdown                        | `exec("ls -A <folder>")` first — read the folder description + `templates_available` before writing |
| Land in an existing repo without orienting      | go straight to `write` when no folder frontmatter / templates exist       | invoke `workflow({ kind: 'discover' })` once for the project — extracts conventions from siblings, sets folder frontmatter + templates, activates the link graph |
| Author a doc when a matching template exists    | `write({ document: { path, content: "..." } })` from scratch                                 | `write({ document: { path, template } })` — templates carry the folder's frontmatter + body discipline |
| Change a doc's title / tags                     | `edit({ document: { path, find, replace } })` to swap the YAML (rejected — HTTP 400 frontmatter-intersect) | `edit({ document: { path, frontmatter } })` for metadata; `write({ document: { path, content, frontmatter, position: "replace" } })` for full rewrites |
| Repeat the same frontmatter on sibling docs     | hand-set identical `tags` / `title` prefix on every new file                       | `write({ template })` once — new docs start from the template |
| Re-derive the same body skeleton repeatedly     | copy-paste the structure from a sibling each time                                  | `write({ template })` once, then pick from `templates_available` thereafter |
| Scaffold a new folder for a doc category        | set folder frontmatter and stop there                                     | pair `edit({ folder })` with `write({ template })` in the same turn |
| Delete a markdown doc                           | `Bash: rm` / `unlink` / native deletion on in-scope `.md`                          | `delete({ document })` — `checkpoint()` first if rollback may be needed |
| Fork a skill and expect no stomp                | Edit installed SKILL.md                                                            | `npx skills remove` before CLI upgrade                                            |

## Workflow tools — when to invoke them

One MCP tool — `workflow` — builds on the primitives above, dispatched on `kind`. **It returns *procedural guidance* (a multi-step instructional body), not fetched data.** Calling `workflow({ kind: 'ingest', source: "https://…" })` does not download and write a doc for you — it returns a multi-step plan you then execute. Same for the `research` / `consolidate` / `discover` kinds. Plan to follow the numbered steps in order; don't skip the STOP gates.

Three kinds correspond to [Karpathy's three-layer knowledge-base pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (`ingest` / `research` / `consolidate`); the fourth (`discover`) operates at the project-metadata layer and is the brownfield counterpart to the greenfield `ok seed` CLI:

| `kind`        | Layer                   | When to invoke (via `workflow({ kind })`)                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ingest`      | Raw sources (immutable) | User shares a URL/PDF/file to preserve verbatim, **OR you fetched a URL** (`WebFetch` / `WebSearch` / equivalent) to ground a claim that's about to land in the knowledge base. The KB is closed-loop — agent-initiated fetches are not exempt. **Binary sources** (PDFs, images, audio, Office docs) are preserved verbatim, not text-scraped — the tool body documents the binary-vs-text classification, write-path STOP gates (executable, size, scheme), re-ingest semantics, and shell-less fallback. No analysis in the file itself — takeaways go back to the user in chat. |
| `research`    | KB, provisional         | User asks you to investigate, compare alternatives, or synthesize multiple sources. Produces a `status: provisional` article with a `sources:` list. Follows scan-first routing, a STOP scoping gate, 3P-external framing, and a validate checklist — the tool body enforces each step. |
| `consolidate` | KB, canonical           | Team has actually decided after research and wants the outcome committed as source-of-truth. Starts with a STOP gate confirming the decision exists; writes a `status: canonical` article with a `supersedes:` chain.                                                                   |
| `discover`    | Project metadata        | First arrival at a repo with existing content AND no folder frontmatter / templates set. Extracts conventions from siblings; activates the link graph (orphans, hubs, untextualized mentions); proposes folder frontmatter + templates + `.okignore`; per-phase user confirmation. Phases 1-4 run fs-direct; Phase 5 (link-graph activation) needs `ok start` (Phase 5 step 0 gates). Skip on empty repos (use `ok seed`). One-shot; idempotent on re-run. |

**These tools are your default move, not `write`.** When the work fits one of the three layers — preserving an external source, investigating/synthesizing, committing a decided outcome — invoke the corresponding tool instead of going straight to `write` / `edit`. The tool bodies enforce framing (sources, status, supersedes chains) that hand-written articles routinely miss. `write` is correct for everything that does **not** fit the three layers (specs, runbooks, scratch notes, project pages); for the three that do, lead with the tool. This is doubly true in projects that ran `ok seed` — a doc landing in `external-sources/` / `research/` / `articles/` should have come out of `ingest` / `research` / `consolidate`.

Typical day-2 flow: user shares a URL → `ingest` (preserve) → user asks "now research this" → `research` (provisional article + `ingest`s more sources as needed) → decision lands → `consolidate` (canonical article, supersedes the research).

**Autonomy gates vs session-level autonomy.** Per-tool STOP gates (e.g. `research`'s scoping gate, `consolidate`'s decision-confirmation gate) are not overridden by session-level "work without stopping for clarifying questions" hints. The session-level hint covers trivial back-and-forth ("which file did you mean?"); per-tool gates exist for 1-way-door decisions where the tool deliberately wants confirmation before continuing. When in doubt, treat the per-tool gate as authoritative and the session-level autonomy hint as a default for the in-between turns.

**Do not chain silently.** After `ingest`, ask the user whether to proceed to `research`. After `research`, let the user decide whether the findings are ready to `consolidate`. Each tool completes on its own terms — the user drives the transitions.

**Repeat invocations.** The `workflow` tool returns its full instructional body on every call, including 2nd / 3rd / Nth invocation in the same session. If you've already received a tool's body earlier this session, you can skim the repeat for changes (the body can evolve across server versions) but you don't need to re-internalize it — proceed to the next step with the new arguments.

**Project scaffolding — two paths.** **Empty repo:** run `ok seed` once from a terminal (scaffolds the layout + seeds `log.md` + folder defaults). **Existing content:** invoke `workflow({ kind: 'discover' })` (table above). Neither is required; the four workflow kinds work against any folder structure. Only mention each when explicitly relevant.

**Starter packs — reference for inspiration.** The `ok` CLI (a Bash surface beside the MCP tools; other verbs `ok start` / `ok open` are documented above) ships proven layouts you can study to build a *similar* structure of your own — adapt the idea, don't clone the pack:

- `knowledge-base` — source-grounded research articles
- `software-lifecycle` — proposals, decisions, specs
- `codebase-wiki` — agent-authored wiki of your codebase
- `plain-notes` — notes + daily journal
- `worldbuilding` — fiction story wiki
- `writing-pipeline` — drafts → published
- `entity-vault` — people / companies / meetings (personal CRM)
- `okf` — Open Knowledge Format–conformant base

To reference one **without installing it**: `ok seed --list-packs` (the menu) → `ok seed --pack <name> --dry-run` (its folders + the *why* of each folder + templates; writes nothing). Then either adapt the ideas into your own folders (`write({ folder })` + a template) or adopt the pack as-is by re-running without `--dry-run`. Reach for this when a user wants structure and an archetype fits — propose a tailored variant, not a verbatim copy.

## Server lifecycle

If `write` or `edit` returns a "Hocuspocus server is not running" error, start it with `ok start` (via Bash) and retry. Never fall back to native `Edit` / `Write` for in-scope markdown — always route through the MCP write tools so edits go through the CRDT with proper attribution.

## Scope recap

OpenKnowledge looks for documents under the resolved `content.dir` (discoverable at runtime via `config({ key: 'content.dir' })`). `.gitignore` and `.okignore` (at the project root and at any folder depth) define exclusions. A folder's own metadata + templates live in nested `<folder>/.ok/frontmatter.yml` + `<folder>/.ok/templates/` — NOT in `.ok/config.yml`.

Default mental model (no jargon): **every `.md` and `.mdx` under `content.dir`** not excluded by `.gitignore` or `.okignore` is an OpenKnowledge document — including under `specs/`, `reports/`, `docs/`, etc. Read `.okignore` (and any nested `.okignore` files) once per turn to know what's excluded.

**First session in this project?** If substantial folders have no frontmatter of their own and no `templates_available`, the project isn't onboarded — invoke `workflow({ kind: 'discover' })` before writing.

**Working in a git worktree?** Pass the worktree's absolute path as `cwd` on your OK tool calls once — it sticks for the rest of the session, so reads, writes, and the preview all target that worktree instead of the main checkout. If a tool warns that it routed to the main checkout while you're in a worktree, passing `cwd` once is the fix.
