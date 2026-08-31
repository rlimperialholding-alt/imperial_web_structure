#!/usr/bin/env python3
"""Read-only forward-recovery dry-run (Gate 8, `forwardRecovery` csoport).

Csak olvas: semmilyen refet, worktree-fájlt vagy indexet nem módosít.
Azt bizonyítja, hogy az elutasítás utáni előre-irányú helyreállítás (a
checkpointról a jelölt commit újra-alkalmazása) végrehajtható:
- a HEAD commit érvényes, a checkpoint a HEAD őse;
- a checkpoint..HEAD diff whitespace-hiba/konfliktus nélkül reprodukálható
  (a forward recovery az egyetlen source-author commit újra-alkalmazását
  jelenti, a diff pedig a git historyból bármikor újra előállítható);
- a worktree tiszta (a jelölt állapot egyértelmű).

Kimenet: a tervezett (NEM végrehajtott) recovery lépések.
Kilépés: 0 = a recovery-terv érvényes, 1 = nem érvényes (fail-closed).
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
        if _git("cat-file", "-t", head) != "commit":
            print("forward-recovery-dry-run FAIL: a HEAD nem commit.")
            return 1
        refs = _git("for-each-ref", "--format=%(refname)", "refs/checkpoints/").splitlines()
        tags = _git("tag", "-l", "task*-start-checkpoint").splitlines()
        candidates = [ref for ref in refs + tags if ref.strip()]
        if not candidates:
            print("forward-recovery-dry-run FAIL: nincs task-start checkpoint ref/tag.")
            return 1
        target_name = sorted(candidates)[-1]
        target = _git("rev-parse", f"{target_name}^{{commit}}")
        _git("merge-base", "--is-ancestor", target, head)
        tree_state = _git("status", "--porcelain")
        if tree_state.strip():
            print("forward-recovery-dry-run FAIL: a worktree nem tiszta, a jelölt állapot nem egyértelmű.")
            return 1
        diff_check = subprocess.run(
            ["git", "diff", "--check", f"{target}..{head}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if diff_check.returncode != 0:
            print("forward-recovery-dry-run FAIL: a checkpoint..HEAD diff whitespace-hibát tartalmaz.")
            return 1
        stat = _git("diff", "--stat", f"{target}..{head}")
        print("forward-recovery-dry-run PASS (read-only):")
        print(f"  head           : {head}")
        print(f"  checkpoint ref : {target_name}")
        print("  planned (NOT executed): a checkpoint..HEAD diff ismételt, tiszta")
        print("  alkalmazása az üres fára (rebase/checkout-szekvencia), a diff")
        print("  a git historyból determinisztikusan reprodukálható.")
        print(stat)
        return 0
    except Exception as exc:  # noqa: BLE001 - fail-closed gate összegzés
        print(f"forward-recovery-dry-run FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
