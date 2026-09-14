#!/usr/bin/env python3
"""Read-only rollback dry-run (Gate 8, `rollback` csoport).

Csak olvas: semmilyen refet, worktree-fájlt vagy indexet nem módosít.
Azt bizonyítja, hogy a fail-closed rollback-visszaállítási terv végrehajtható:
a legutóbbi task-start checkpoint ref létezik, a jelenlegi HEAD őse, a
visszaállítási cél egy commit, és a worktree a jelölt állapotban van.

Kimenet: a tervezett (NEM végrehajtott) rollback lépések és a célelv.
Kilépés: 0 = a rollback-terv érvényes, 1 = a terv nem érvényes (fail-closed).
"""

from __future__ import annotations

import subprocess
import sys


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def main() -> int:
    try:
        head = _git("rev-parse", "HEAD")
        # A legutóbbi task-start checkpoint: a `task*-start` név a checkpoint-
        # konvenció; az utolsó munkamenet indulási állapotára mutat.
        refs = _git("for-each-ref", "--format=%(refname)", "refs/checkpoints/").splitlines()
        tags = _git("tag", "-l", "task*-start-checkpoint").splitlines()
        candidates = [ref for ref in refs + tags if ref.strip()]
        if not candidates:
            print("rollback-dry-run FAIL: nincs task-start checkpoint ref/tag.")
            return 1
        target_name = sorted(candidates)[-1]
        target = _git("rev-parse", f"{target_name}^{{commit}}")
        _git("merge-base", "--is-ancestor", target, head)
        if target == head:
            print("rollback-dry-run FAIL: a checkpoint egyezik a HEAD-del, nincs mit visszaállítani.")
            return 1
        tree_state = _git("status", "--porcelain")
        if tree_state.strip():
            print("rollback-dry-run FAIL: a worktree nem tiszta, a rollback-terv nem egyértelmű.")
            return 1
        print("rollback-dry-run PASS (read-only):")
        print(f"  head           : {head}")
        print(f"  checkpoint ref : {target_name}")
        print(f"  restore target : {target}")
        print("  planned (NOT executed): git reset --hard <target>; git clean -fd (protected dirs kept)")
        return 0
    except Exception as exc:  # noqa: BLE001 - fail-closed gate összegzés
        print(f"rollback-dry-run FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
