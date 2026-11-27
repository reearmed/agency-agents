"""Guard against package-import regressions in the future HTTP service."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


BUSINESS_OS_ROOT = Path(__file__).resolve().parents[1]


class PackageImportTests(unittest.TestCase):
    def test_all_runtime_modules_import_as_a_package(self):
        modules = (
            "control_plane.guardrails",
            "control_plane.identity_boundary",
            "control_plane.auth0_jwt_verifier",
            "control_plane.approval_grants",
            "control_plane.execution_gateway",
            "control_plane.durable_execution",
            "control_plane.sqlite_store",
            "control_plane.independent_verifier",
            "control_plane.route_authorization",
            "control_plane.cli",
            "control_plane.http_api",
            "control_plane.synthetic_e2e",
        )
        code = (
            "import importlib; "
            + "; ".join(f"importlib.import_module({module!r})" for module in modules)
        )
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(BUSINESS_OS_ROOT) + (
            os.pathsep + existing if existing else ""
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=BUSINESS_OS_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"package import failed:\nstdout={result.stdout}\nstderr={result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
