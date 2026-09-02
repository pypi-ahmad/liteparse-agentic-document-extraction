# Operations

Install and run:

```powershell
uv sync --all-groups --locked
uv run liteparse-ade
```

The app binds to `127.0.0.1:9578`. `launch.cmd` intentionally terminates the current listener
on that port before launching. `OPENAI_API_KEY` must exist in the process environment;
`OPENAI_BASE_URL` is honored when configured. Secrets must never be copied into project files.

Uploads, OCR caches, and artifacts are session-local. Model requests set `store=False`.
