from __future__ import annotations

import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from approval_grants import ApprovalGrantAuthority, SQLiteGrantLedger
from cli import main
from durable_execution import DurableMockExecutionGateway, SQLiteMockAdapter
from execution_gateway import MockOutcomeVerifier


class LocalLedgerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_verify_requires_existing_database_and_does_not_create_one(self):
        db = self.root / "missing.sqlite3"
        code, _, error = self.run_cli("verify", "--db", str(db))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", error)
        self.assertFalse(db.exists())

    def test_configure_budget_creates_private_database_and_reports_usage(self):
        db = self.root / "ledger" / "business-os.sqlite3"
        code, output, _ = self.run_cli(
            "configure-budget", "--db", str(db), "--period", "2026-11",
            "--monthly-limit-minor", "5000", "--per-task-limit-minor", "1000",
            "--currency", "USD",
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["configured"])
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(db.parent.stat().st_mode), 0o700)
        code, output, _ = self.run_cli("budget-usage", "--db", str(db), "--period", "2026-11")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["remaining_minor"], 5000)

    def test_budget_limit_cannot_be_increased_through_cli(self):
        db = self.root / "ledger.sqlite3"
        self.run_cli(
            "configure-budget", "--db", str(db), "--period", "2026-11",
            "--monthly-limit-minor", "5000", "--per-task-limit-minor", "1000",
            "--currency", "USD",
        )
        code, _, error = self.run_cli(
            "configure-budget", "--db", str(db), "--period", "2026-11",
            "--monthly-limit-minor", "9000", "--per-task-limit-minor", "1000",
            "--currency", "USD",
        )
        self.assertEqual(code, 2)
        self.assertIn("controlled offline migration", error)

    def test_kill_switch_cli_is_one_way_and_persistent(self):
        db = self.root / "ledger.sqlite3"
        SQLiteGrantLedger(db)
        code, output, _ = self.run_cli("activate-kill-switch", "--db", str(db))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["kill_switch_active"])
        self.assertTrue(SQLiteGrantLedger(db).kill_switch_active())
        code, output, _ = self.run_cli("verify", "--db", str(db))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["kill_switch_active"])
        with self.assertRaises(SystemExit):
            main(["clear-kill-switch", "--db", str(db)])

    def test_intents_cli_lists_safe_summaries_without_operation_payload(self):
        db = self.root / "ledger.sqlite3"
        ledger = SQLiteGrantLedger(db)
        authority = ApprovalGrantAuthority(
            signing_key=b"cli-test-signing-key-material-32-bytes",
            ledger=ledger,
            identity_verifier=lambda actor, context: context == "trusted",
        )
        gateway = DurableMockExecutionGateway(
            authority=authority,
            ledger=ledger,
            adapter=SQLiteMockAdapter(ledger),
            verifier=MockOutcomeVerifier(),
            kill_switch_check=lambda: False,
        )
        payload = {"operation": "private-synthetic-payload"}
        token = authority.issue(
            task_id="cli-task-0001", payload=payload, adapter="mock",
            action="create", target="isolated-target", idempotency_key="cli-idem-0001",
            requester_id="agent", approver_id="human", auth_context="trusted",
        )
        gateway.submit(
            token, task_id="cli-task-0001", payload=payload, adapter_name="mock",
            action="create", target="isolated-target", idempotency_key="cli-idem-0001",
            requester_id="agent",
        )
        code, output, _ = self.run_cli("intents", "--db", str(db), "--state", "VERIFY_PENDING")
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["task_id"], "cli-task-0001")
        self.assertNotIn("operation_json", result[0])
        self.assertNotIn("private-synthetic-payload", output)

    def test_backup_cli_creates_private_verified_backup(self):
        db = self.root / "ledger.sqlite3"
        SQLiteGrantLedger(db)
        backup = self.root / "backups" / "verified.sqlite3"
        code, output, _ = self.run_cli("backup", "--db", str(db), "--destination", str(backup))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["verified"])
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertTrue(SQLiteGrantLedger(backup).verify_all()["ok"])

    def test_cli_rejects_relative_database_path(self):
        code, _, error = self.run_cli("verify", "--db", "relative.sqlite3")
        self.assertEqual(code, 2)
        self.assertIn("absolute", error)


if __name__ == "__main__":
    unittest.main()
