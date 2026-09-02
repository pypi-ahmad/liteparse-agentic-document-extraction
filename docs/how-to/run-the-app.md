# How to run the app

## Install

From PowerShell:

```powershell
git clone https://github.com/pypi-ahmad/liteparse-agentic-document-extraction.git
cd liteparse-agentic-document-extraction
uv sync --all-groups --locked
```

The application reads `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from its process
environment. Do not place credentials in the repository. Configure credentials through Windows
user environment settings, restart PowerShell, then verify presence without printing the value:

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OPENAI_API_KEY is unavailable; restart PowerShell after configuring it."
}
```

The endpoint must support the Responses API, strict structured output, image input, and
`gpt-5.6-terra`. An `OPENAI_BASE_URL` override selects that endpoint for the SDK.

## Start from PowerShell

```powershell
uv run liteparse-ade
```

Open <http://127.0.0.1:9578>. Stop the app with <kbd>Ctrl</kbd>+<kbd>C</kbd> in its terminal.

## Start with the Windows launcher

Double-click `launch.cmd`, or run:

```powershell
.\launch.cmd
```

The launcher forcibly terminates any process listening on port `9578`, then starts the app.
Save unrelated work before using it if another service may own that port.

## Use another port

Set the port for the current PowerShell process before starting:

```powershell
$env:LITEPARSE_APP_PORT = "9580"
uv run liteparse-ade
```

Do not use `launch.cmd` for a custom port; it always resets the port to `9578`.

## Update dependencies

Reproduce the locked environment with:

```powershell
uv sync --all-groups --locked
```

Use `uv sync` without `--locked` only when intentionally updating dependency resolution and
review the resulting lock-file change.

See [troubleshooting](troubleshooting.md) if the app does not start.
