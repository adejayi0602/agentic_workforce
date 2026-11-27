"""The worker runs the processing code without the API app around it. In a fresh interpreter,
importing what the worker imports must leave every ORM mapping resolvable."""

import subprocess
import sys

SCRIPT = """
import workforce_workers.worker  # what `python -m workforce_workers.worker` loads
from workforce_api.db.base import Base

# Resolving each foreign key's target raises if that table was never imported, which is
# exactly what happens on the worker's first insert otherwise.
for table in Base.metadata.tables.values():
    for fk in table.foreign_keys:
        fk.column
print("ok")
"""


def test_worker_imports_resolve_every_mapping() -> None:
    result = subprocess.run(  # noqa: S603 - fixed script, test-only
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
