from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_package_import_is_side_effect_free_with_configured_api_key() -> None:
    adapter_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["MEM0_API_KEY"] = "must-not-initialize-a-client"
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(adapter_root), env.get("PYTHONPATH")) if item
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import mem0_platform_adapter; "
                "assert 'mem0_platform_adapter.app' not in sys.modules; "
                "assert 'mem0_platform_adapter.sdk_platform' not in sys.modules; "
                "assert 'mem0' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
