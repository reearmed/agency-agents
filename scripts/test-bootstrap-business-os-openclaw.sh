#!/usr/bin/env bash
# Synthetic safety tests for the Business OS workspace bootstrapper.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/bootstrap-business-os-openclaw.sh"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

SYNTHETIC_REPO="$TMP_ROOT/repo"
mkdir -p "$SYNTHETIC_REPO/scripts" "$SYNTHETIC_REPO/business-os/agents"
cp "$SCRIPT" "$SYNTHETIC_REPO/scripts/bootstrap-business-os-openclaw.sh"
cp "$REPO_ROOT/business-os/AUTONOMY.md" "$SYNTHETIC_REPO/business-os/AUTONOMY.md"
cp "$REPO_ROOT/business-os/TASK_CONTRACT.md" "$SYNTHETIC_REPO/business-os/TASK_CONTRACT.md"
cp -R "$REPO_ROOT/business-os/agents/." "$SYNTHETIC_REPO/business-os/agents/"
SYNTHETIC_SCRIPT="$SYNTHETIC_REPO/scripts/bootstrap-business-os-openclaw.sh"

# Default dry-run must not create the workspace root.
DRY_ROOT="$TMP_ROOT/dry-run"
OPENCLAW_BUSINESS_OS_HOME="$DRY_ROOT" bash "$SYNTHETIC_SCRIPT" >/dev/null
[[ ! -e "$DRY_ROOT" ]] || { echo "dry-run created files" >&2; exit 1; }

# Apply must create nine private workspaces with five files each.
APPLY_ROOT="$TMP_ROOT/applied"
OPENCLAW_BUSINESS_OS_HOME="$APPLY_ROOT" bash "$SYNTHETIC_SCRIPT" --apply >/dev/null
python3 - "$APPLY_ROOT" <<'PY'
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
agents = list(root.iterdir())
assert len(agents) == 9, f"expected 9 workspaces, found {len(agents)}"
for agent in agents:
    assert agent.is_dir() and not agent.is_symlink()
    assert stat.S_IMODE(agent.stat().st_mode) == 0o700
    files = list(agent.iterdir())
    assert len(files) == 5, f"{agent}: expected 5 files, found {len(files)}"
    for item in files:
        assert item.is_file() and not item.is_symlink()
        assert stat.S_IMODE(item.stat().st_mode) & 0o077 == 0
assert stat.S_IMODE(root.stat().st_mode) == 0o700
PY

# A second apply must fail rather than overwrite any existing file.
if OPENCLAW_BUSINESS_OS_HOME="$APPLY_ROOT" bash "$SYNTHETIC_SCRIPT" --apply >/dev/null 2>&1; then
  echo "second apply unexpectedly succeeded" >&2
  exit 1
fi

# Reject relative roots and symlinked roots.
if OPENCLAW_BUSINESS_OS_HOME="relative-business-os" bash "$SYNTHETIC_SCRIPT" >/dev/null 2>&1; then
  echo "relative destination unexpectedly accepted" >&2
  exit 1
fi
mkdir "$TMP_ROOT/real-root"
ln -s "$TMP_ROOT/real-root" "$TMP_ROOT/root-link"
if OPENCLAW_BUSINESS_OS_HOME="$TMP_ROOT/root-link" bash "$SYNTHETIC_SCRIPT" >/dev/null 2>&1; then
  echo "symlinked destination unexpectedly accepted" >&2
  exit 1
fi

# Reject existing broad-permission roots and symlinked agent workspaces.
mkdir "$TMP_ROOT/broad-root"
chmod 755 "$TMP_ROOT/broad-root"
if OPENCLAW_BUSINESS_OS_HOME="$TMP_ROOT/broad-root" bash "$SYNTHETIC_SCRIPT" >/dev/null 2>&1; then
  echo "broad-permission destination unexpectedly accepted" >&2
  exit 1
fi
mkdir "$TMP_ROOT/symlink-root" "$TMP_ROOT/outside"
chmod 700 "$TMP_ROOT/symlink-root"
ln -s "$TMP_ROOT/outside" "$TMP_ROOT/symlink-root/orchestrator"
if OPENCLAW_BUSINESS_OS_HOME="$TMP_ROOT/symlink-root" bash "$SYNTHETIC_SCRIPT" >/dev/null 2>&1; then
  echo "symlinked workspace unexpectedly accepted" >&2
  exit 1
fi

echo "PASS bootstrap dry-run, apply, permissions, no-overwrite and path safety"
