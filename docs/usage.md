# Usage

Nexus is a streaming chat interface backed by a tool-using model. This guide covers the model, the built-in tools, files and links, and the visible goal/task system.

## The model

The curated model is **Nemotron 3.5 VL Super** (NVIDIA, 120B vision-language, 1M-token context, native tool calling). It is automatically preferred on NVIDIA NIM, falling back to OpenRouter. Custom models (any OpenAI-compatible model ID) can be added in Settings and route through OpenRouter.

## Built-in tools

The model chooses which tools to call. Each tool returns structured output that the model reads directly. Full tool schemas: [tools.md](./tools.md).

| Tool | What it does |
|------|--------------|
| `web_search` | Live web search through a local SearXNG instance. Returns titles, URLs, snippets, and engines. |
| `web_fetch` | Read a public page as Markdown. Only public http(s) URLs; blocks private/loopback/link-local addresses (DNS-rebinding safe). |
| `write_file` | Create or overwrite a UTF-8 file in this chat's outputs folder. Returns a `file://` markdown link. |
| `read_file` | Read a text file from outputs, uploads, or workspace. Images and PDFs are rendered as native visual content; PDFs also return their text layer. |
| `list_files` | List this chat's uploads (read-only), outputs (writable), and workspace scratch files. |
| `sandbox` | Run a shell command in an isolated Linux container (Python, git, curl, Node, compiler). |
| `note_list` / `note_get` / `note_set` / `note_delete` | Read and save durable notes about the user (preferences, lasting facts). |
| `task_create` / `task_update` / `task_list` / `set_goal` | Manage the conversation's visible goal and task list. |

## Working style (system prompt)

The system prompt instructs the model to:

1. **Use tools instead of guessing.** For multi-step work, first `set_goal`, then create 2–6 concrete tasks. Keep exactly one task `in_progress`, update it as you go, and mark it done immediately when finished. Do not create tasks for simple one-shot questions.
2. **Never invent search results, file contents, or code output.** If a tool fails, say what failed and try a sensible alternative.
3. **Prefer primary sources.** Cite the URLs you actually used as normal Markdown links.
4. **For current information, search even if you think you know the answer.** Training data may be stale.
5. **Use Python for complex math.** Multi-step arithmetic, algebra, statistics, unit conversions, and financial calculations go in the sandbox, not in reasoning.
6. **Be concise by default.** Use Markdown structure only when it helps. Do not narrate every tool call.

## Files and links

- Uploads: `useruploads/` (model reads them at `/mnt/useruploads`)
- Outputs: `outputs/` (model writes them at `/mnt/outputs`)
- Per-chat scratch: `.workspaces/<chat-id>` (mounted at `/workspace`)

The model is instructed to produce `file://` links under `/mnt/outputs`. The frontend maps those to `/api/files/...`, and active content (HTML, SVG, XML, JavaScript) is served as `text/plain` with a sandbox CSP rather than rendered on the app origin.

Always link files exactly as:

```markdown
[Report.md](file:///mnt/outputs/Report.md)
```

Use the link returned by `write_file`. Never claim a file exists unless you actually wrote it.

## Message versions (editing & regeneration)

Every edit or regenerate appends a new version to a message instead of overwriting it. The user can switch between versions with the version switcher on each message. Switching versions re-renders the message without contacting the model; the active version is what's sent as context in later turns.

## Settings

Settings live in the database (provider, API keys, user name, temperature, custom instructions, custom model ID, custom models) and are editable in the Settings dialog. Environment variables provide defaults; database values override them per-instance.
