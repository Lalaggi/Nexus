# Tool reference

Nexus exposes a curated set of tools to the model. Each tool is a JSON-schema function call with a name, description, parameters, and a handler. Tools never kill the stream — a tool failure is returned as a structured error message the model can read and act on.

## Web search — `web_search`

Search the live web via a local SearXNG instance.

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | The search query |
| `num_results` | integer | no | How many results to return (1–10) |
| `time_range` | enum | no | Recency filter: `day`, `week`, `month`, `year` |

**Behavior**

- Returns titles, URLs, snippets (≤400 chars), and engines.
- Falls back to "no results" guidance when empty.

## Web fetch — `web_fetch`

Read a public page and extract its readable text as Markdown.

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes | Absolute http(s) URL |
| `max_chars` | integer | no | Max extracted characters (1000–60000, default 20000) |

**Behavior**

- Only public http(s) addresses. Private, loopback, link-local, and `.local` hosts are blocked.
- The hostname is resolved once and the connection is pinned to that IP (DNS-rebinding safe); the original hostname is kept for `Host`, SNI, and certificate checks.
- Follows up to 6 redirects. Caps the body at 3 MB.
- HTML is extracted with trafilatura (with a regex fallback); PDFs are parsed with pypdf; JSON and plain text pass through.
- Returns the title, final URL, and extracted text.

## Write file — `write_file`

Create or overwrite a UTF-8 file in this chat's user-visible outputs folder.

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Destination filename inside outputs, optionally with subfolders (e.g. `report.md`, `charts/sales.png`, or `/mnt/outputs/report.md`) |
| `content` | string | yes | Full UTF-8 file content |

**Behavior**

- Writes atomically via a temp file then `replace`.
- 8 MB content limit.
- Returns a `file://` markdown link the model should give the user.

## Read file — `read_file`

Read a text file from outputs, uploads, or `/workspace`. Images and PDFs are rendered as native visual content for vision-capable models.

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | File to read. A bare filename is looked up in outputs, uploads, then workspace. Paths like `/mnt/outputs/report.md` also work. |
| `max_chars` | integer | no | Max characters (1000–100000, default 30000) |

**Behavior**

- Images (PNG/JPEG/WebP/GIF/BMP/TIFF) and PDFs are rendered as base64 JPEG image parts; PDFs also return their extracted text layer.
- Text-only models fall back to extracted text for PDFs, and report that images cannot be viewed natively.
- Binary files are rejected (use the sandbox with `file`, `unzip -l`, or a Python script instead).

## List files — `list_files`

List this chat's uploaded files, user-visible outputs, and workspace scratch files.

**Parameters:** none.

**Behavior**

- Returns uploads (read-only), outputs (writable, clickable), and workspace scratch files (text-only listing).
- Workspace files are not user-visible.

## Sandbox — `sandbox`

Run a shell command in an isolated Linux container.

**Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | yes | Shell command to run |
| `timeout` | integer | no | Seconds before the command is killed (default 90, max 180) |

**Behavior**

- Working directory is `/workspace` (persists for this conversation).
- Uploads are read-only at `/mnt/useruploads`; write anything the user should see to `/mnt/outputs`.
- Has Python, git, curl, Node, a compiler, and common CLI tools, plus internet access for public resources.
- Ephemeral container: read-only root, dropped capabilities, `no-new-privileges`, memory/CPU/PID limits, no host home, no app database.
- `/workspace/.python-packages` persists pip installs across calls (on `PYTHONPATH`).
- Returns exit code, stdout/stderr (truncated), and lists new/updated files in outputs with `file://` links.

## User notes — `note_list` / `note_get` / `note_set` / `note_delete`

Read and save durable notes about the user (preferences, lasting facts). Notes are user-level, not per-chat.

| Tool | Parameters |
|------|------------|
| `note_list` | none |
| `note_get` | `key` (string) |
| `note_set` | `key` (string, lowercase, letters/numbers/dashes/underscores, max 60), `value` (string, max 1000) |
| `note_delete` | `key` (string) |

**Guidance:** only save important, lasting facts (e.g. a preferred editor). Do not save trivial or conversation-specific details.

## Goal & tasks — `task_create` / `task_update` / `task_list` / `set_goal`

Manage the conversation's visible goal and task list.

| Tool | Parameters |
|------|------------|
| `task_create` | `title` (string), `detail` (string, optional), `status` (`pending`\|`in_progress`\|`done`\|`blocked`, optional) |
| `task_update` | `task_id` (string), `status`/`title`/`detail` (optional) |
| `task_list` | none |
| `set_goal` | `goal` (string) |

**Guidance:** for multi-step work, `set_goal` once, then create 2–6 concrete tasks. Keep exactly one task `in_progress`.
