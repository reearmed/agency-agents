"""Human-operated, read-only-by-default CLI for the local Business OS ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from approval_grants import GrantError, SQLiteGrantLedger


def _ledger(path_text: str, *, require_existing: bool = True) -> SQLiteGrantLedger:
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError("database path must be absolute")
    if path.is_symlink():
        raise ValueError("database path must not be a symlink")
    if require_existing and (not path.exists() or not path.is_file()):
        raise ValueError("database file does not exist")
    return SQLiteGrantLedger(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Business OS control-plane ledger operations")
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="Run read-only SQLite, audit, intent, budget and receipt checks")
    verify.add_argument("--db", required=True)

    configure = sub.add_parser("configure-budget", help="Set a period budget once; no application-side increase")
    configure.add_argument("--db", required=True)
    configure.add_argument("--period", required=True)
    configure.add_argument("--monthly-limit-minor", required=True, type=int)
    configure.add_argument("--per-task-limit-minor", required=True, type=int)
    configure.add_argument("--currency", required=True)

    usage = sub.add_parser("budget-usage", help="Read reserved and settled budget totals")
    usage.add_argument("--db", required=True)
    usage.add_argument("--period", required=True)

    pause = sub.add_parser("activate-kill-switch", help="Persist the emergency stop; no CLI clear command exists")
    pause.add_argument("--db", required=True)

    backup = sub.add_parser("backup", help="Create a new private verified SQLite backup")
    backup.add_argument("--db", required=True)
    backup.add_argument("--destination", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "configure-budget":
            ledger = _ledger(args.db, require_existing=False)
            ledger.configure_budget(
                period=args.period,
                monthly_limit_minor=args.monthly_limit_minor,
                per_task_limit_minor=args.per_task_limit_minor,
                currency=args.currency,
            )
            result = {"configured": True, "period": args.period, "currency": args.currency}
        else:
            ledger = _ledger(args.db)
            if args.command == "verify":
                result = ledger.verify_all()
                print(json.dumps(result, sort_keys=True))
                return 0 if result["ok"] else 2
            if args.command == "budget-usage":
                result = ledger.budget_usage(args.period)
            elif args.command == "activate-kill-switch":
                ledger.activate_kill_switch()
                result = {"kill_switch_active": ledger.kill_switch_active()}
            elif args.command == "backup":
                created = ledger.backup_to(args.destination)
                result = {"backup_path": str(created), "verified": True}
            else:
                raise ValueError("unsupported command")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (GrantError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
