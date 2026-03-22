from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _provider_env_present() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or (os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"))
        or os.getenv("OLLAMA_BASE_URL")
    )


def _provider_regression_enabled() -> bool:
    return os.getenv("ALIGNHUB_RUN_REAL_PROVIDER_TESTS") == "1" and _provider_env_present()


class LangGraphScriptTests(unittest.TestCase):
    maxDiff = None

    def _run_script(self, script_name: str, *, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        return subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "scripts" / script_name)],
            cwd=str(REPO_ROOT),
            env=run_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )

    def test_langgraph_smoke_script(self) -> None:
        with tempfile.TemporaryDirectory(prefix="alignhub-langgraph-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            env = {
                "APP_DATABASE_URL": _sqlite_url(temp_root / "smoke.db"),
                "APP_LANGGRAPH_CHECKPOINT_PATH": str((temp_root / "langgraph_checkpoints.sqlite").resolve()),
                "APP_ARTIFACT_ROOT": str((temp_root / "artifacts").resolve()),
                "APP_WORKSPACE_ROOT": str(REPO_ROOT.resolve()),
                "APP_CLEANUP_RUN_WORKSPACE_ON_FINISH": "false",
            }
            result = self._run_script("langgraph_smoke_test.py", env=env)
            self.assertIn("langgraph smoke test passed", result.stdout)

    def test_langgraph_recovery_script(self) -> None:
        result = self._run_script("langgraph_recovery_test.py", timeout=240)
        self.assertIn("langgraph recovery test passed", result.stdout)

    def test_langgraph_realtime_script(self) -> None:
        with tempfile.TemporaryDirectory(prefix="alignhub-langgraph-realtime-") as temp_dir:
            temp_root = Path(temp_dir)
            env = {
                "APP_DATABASE_URL": _sqlite_url(temp_root / "realtime.db"),
                "APP_LANGGRAPH_CHECKPOINT_PATH": str((temp_root / "langgraph_checkpoints.sqlite").resolve()),
                "APP_ARTIFACT_ROOT": str((temp_root / "artifacts").resolve()),
                "APP_WORKSPACE_ROOT": str(REPO_ROOT.resolve()),
                "APP_CLEANUP_RUN_WORKSPACE_ON_FINISH": "false",
            }
            result = self._run_script("langgraph_realtime_test.py", env=env)
            self.assertIn("langgraph realtime test passed", result.stdout)

    def test_langgraph_deletion_script(self) -> None:
        with tempfile.TemporaryDirectory(prefix="alignhub-langgraph-delete-") as temp_dir:
            temp_root = Path(temp_dir)
            env = {
                "APP_DATABASE_URL": _sqlite_url(temp_root / "delete.db"),
                "APP_LANGGRAPH_CHECKPOINT_PATH": str((temp_root / "langgraph_checkpoints.sqlite").resolve()),
                "APP_ARTIFACT_ROOT": str((temp_root / "artifacts").resolve()),
                "APP_WORKSPACE_ROOT": str(REPO_ROOT.resolve()),
                "APP_CLEANUP_RUN_WORKSPACE_ON_FINISH": "false",
            }
            result = self._run_script("langgraph_deletion_test.py", env=env)
            self.assertIn("langgraph deletion test passed", result.stdout)

    def test_langgraph_moderator_validation_script(self) -> None:
        with tempfile.TemporaryDirectory(prefix="alignhub-langgraph-moderator-") as temp_dir:
            temp_root = Path(temp_dir)
            env = {
                "APP_DATABASE_URL": _sqlite_url(temp_root / "moderator.db"),
                "APP_LANGGRAPH_CHECKPOINT_PATH": str((temp_root / "langgraph_checkpoints.sqlite").resolve()),
                "APP_ARTIFACT_ROOT": str((temp_root / "artifacts").resolve()),
                "APP_WORKSPACE_ROOT": str(REPO_ROOT.resolve()),
                "APP_CLEANUP_RUN_WORKSPACE_ON_FINISH": "false",
            }
            result = self._run_script("langgraph_moderator_validation_test.py", env=env)
            self.assertIn("langgraph moderator validation test passed", result.stdout)

    @unittest.skipUnless(_provider_regression_enabled(), "Real provider regression is opt-in via ALIGNHUB_RUN_REAL_PROVIDER_TESTS=1")
    def test_langgraph_provider_regression_script(self) -> None:
        result = self._run_script("langgraph_provider_regression.py", timeout=600)
        self.assertIn("langgraph provider regression passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
