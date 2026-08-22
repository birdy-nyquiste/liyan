import os
import subprocess
import sys
from pathlib import Path


def test_migrations_bootstrap_an_empty_database(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    database_path = tmp_path / "liyan.db"
    environment = os.environ | {
        "LIYAN_DATABASE_URL": f"sqlite+pysqlite:///{database_path}",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
