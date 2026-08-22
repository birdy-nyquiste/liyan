import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy


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


def _upgraded_database(tmp_path: Path) -> sqlalchemy.Engine:
    project_root = Path(__file__).resolve().parents[3]
    database_url = f"sqlite+pysqlite:///{tmp_path / 'liyan.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=os.environ | {"LIYAN_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return sqlalchemy.create_engine(database_url)


def test_executions_keep_one_active_run_per_target_without_a_target_foreign_key(
    tmp_path: Path,
) -> None:
    engine = _upgraded_database(tmp_path)
    inspector = sqlalchemy.inspect(engine)

    target_keys = [
        key
        for key in inspector.get_foreign_keys("executions")
        if key["constrained_columns"] == ["target_id"]
    ]
    active_index = next(
        index
        for index in inspector.get_indexes("executions")
        if index["name"] == "uq_executions_one_active_per_target"
    )

    assert target_keys == []
    assert active_index["unique"]
    assert active_index["column_names"] == ["target_id"]
    with engine.connect() as connection:
        definition = connection.execute(
            sqlalchemy.text(
                "SELECT sql FROM sqlite_master "
                "WHERE name = 'uq_executions_one_active_per_target'"
            )
        ).scalar_one()
    assert "cancel_requested" in definition
    assert {"owner_id", "input_version", "attempt", "result_id"} <= {
        column["name"] for column in inspector.get_columns("executions")
    }
    assert "zhiyan_reports" in inspector.get_table_names()
