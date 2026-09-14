"""Regression checks for the Windows launcher."""

from pathlib import Path


def test_launcher_keeps_live_logs_visible() -> None:
    launcher = Path("launch.cmd").read_text(encoding="utf-8")

    assert 'set "PYTHONUNBUFFERED=1"' in launcher
    assert 'set "STREAMLIT_LOGGER_LEVEL=info"' in launcher
    assert "uv run --no-sync liteparse-ade" in launcher
    assert "pause" in launcher


def test_launcher_releases_the_previous_app_process_tree() -> None:
    launcher = Path("launch.cmd").read_text(encoding="utf-8")
    stop_script = Path("scripts/stop-port-process.ps1").read_text(encoding="utf-8")

    assert "stop-port-process.ps1" in launcher
    assert "if errorlevel 1" in launcher
    assert "taskkill.exe /PID $rootProcess.ProcessId /T /F" in stop_script
    assert "AddSeconds(10)" in stop_script
