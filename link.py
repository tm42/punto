#!/usr/bin/env python3
"""Install this repo's dotfiles into $HOME as symlinks, and report what it did.

    ./link.py [--dry-run] [--prune]

The sibling of check.py's `links` section, and deliberately the only half that
writes. check.py already walks every package and sorts every managed path into
the seven states a path in $HOME can be in; this file is one policy per state
plus the write, importing that walk rather than restating it. A file added to a
package is therefore linked here and reported as missing there with no table to
update in either program.

This used to be a shell loop pasted out of INSTALL.md, which is why a new file in
an existing package went unlinked after a pull: balance.sh landed in 260d71f and
`M-e l` returned 127 on a second machine, because ~/.tmux/balance.sh did not
exist. ~/.tmux is a real directory rather than a folded link — tpm owns
~/.tmux/plugins/ — so every file in that package needs its own symlink.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import check
from check import HOME, PKGROOT, REPO, managed, packages, stale_links

BACKUP_ROOT = HOME / "punto-backup"


# ── What a path in $HOME is, and what to do about it ─────────────────────────

# The states check.py's classifier can produce, and this file's policy for each.
# Keys are the verdicts; the value is what the write does.
#
#   linked                     nothing
#   missing                    create it
#   same content               replace, no backup — there is nothing to lose
#   different content          back up, then replace
#   wrong file in this repo    relink, printing the old target
#   outside this repo          relink, printing the old target
#   broken link                relink
#
# Only the two "real file" cases differ from each other, and only in whether a
# backup happens, which is why the content comparison is worth making: the loop
# this replaces saved both, so a file identical to the repo copy became a backup
# nobody would ever read.


def classify(src: Path, dst: Path) -> str:
    """What `dst` is, relative to the repo file `src` that should own it.

    The same seven verdicts check_links reports, by the same tests, so the two
    programs cannot disagree about a path. Kept here rather than imported
    because check_links prints as it goes and returns nothing."""
    if dst.is_symlink():
        try:
            resolved = dst.resolve()
        except OSError:
            return "broken link"
        if resolved == src.resolve():
            return "linked"
        return ("wrong file in this repo" if REPO in resolved.parents
                else "outside this repo")
    if not dst.exists():
        return "missing"
    try:
        same = src.read_bytes() == dst.read_bytes()
    except OSError:
        same = False
    return "same content" if same else "different content"


def symlinked_parent(rel: Path) -> Path | None:
    """The first parent of `rel` inside $HOME that is itself a symlink.

    Refused rather than worked around. `ln -sfn`'s -n guards a symlink named as
    the target itself and never one in a parent, so with ~/.config/nvim pointing
    at another checkout, linking ~/.config/nvim/init.lua replaces a file inside
    *that* repository — outside $HOME entirely."""
    for parent in list(rel.parents)[:-1]:      # drops ".", which is $HOME
        if (HOME / parent).is_symlink():
            return parent
    return None


# ── The plan, and carrying it out ───────────────────────────────────────────


def plan() -> tuple[list, list]:
    """(actions, refusals) over every managed path in every package.

    An action is (verdict, pkg, rel). A refusal is (rel, symlinked parent)."""
    actions, refused = [], []
    for pkg in packages():
        for rel in managed(pkg):
            blocker = symlinked_parent(rel)
            if blocker is not None:
                refused.append((rel, blocker))
                continue
            verdict = classify(PKGROOT / pkg / rel, HOME / rel)
            if verdict != "linked":
                actions.append((verdict, pkg, rel))
    return actions, refused


def do_link(pkg: str, rel: Path, verdict: str, stamp: str) -> None:
    src, dst = PKGROOT / pkg / rel, HOME / rel
    if verdict == "different content":
        bk = BACKUP_ROOT / stamp / rel
        bk.parent.mkdir(parents=True, exist_ok=True)
        dst.rename(bk)
        print(f"  saved   {rel}  ->  {check.tilde(bk)}")
    elif verdict in ("wrong file in this repo", "outside this repo"):
        print(f"  relink  {rel}  (was -> {dst.readlink()})")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)


def main() -> int:
    args = set(sys.argv[1:])
    unknown = args - {"--dry-run", "--prune", "-h", "--help"}
    if unknown:
        print(f"no such option: {' '.join(sorted(unknown))}\n"
              "usage: ./link.py [--dry-run] [--prune]", file=sys.stderr)
        return 2
    if args & {"-h", "--help"}:
        print(__doc__)
        return 0
    dry, prune = "--dry-run" in args, "--prune" in args

    actions, refused = plan()
    stale = stale_links()

    check.say("link" + ("  (dry run — nothing is written)" if dry else ""))
    if not actions and not refused:
        check.ok(f"every managed file is linked  ({sum(len(managed(p)) for p in packages())} files)")
    for verdict, pkg, rel in actions:
        print(f"  {'would link' if dry else 'link  '}  {rel}  ({verdict})")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    failed = 0
    if not dry:
        for verdict, pkg, rel in actions:
            try:
                do_link(pkg, rel, verdict, stamp)
            except OSError as e:
                check.bad(f"{rel}: {e}")
                failed += 1
    for rel, blocker in refused:
        # Named rather than skipped silently: the file stays unlinked until the
        # parent is dealt with, and nothing else would ever say so.
        check.warn(f"{rel}: refused — parent {blocker} is a symlink; "
                   "move or remove it and re-run")

    if stale:
        check.say("stale links")
        for rel, target in stale:
            if prune:
                if dry:
                    print(f"  would prune  {rel}  ->  {check.tilde(target)}")
                else:
                    (HOME / rel).unlink()
                    print(f"  pruned  {rel}  ->  {check.tilde(target)}")
            else:
                check.warn(f"{rel} -> {check.tilde(target)} — points into this "
                           "repo at a path no package owns; --prune deletes it")

    print()
    if failed:
        print(f"{check.RED}✘ {failed} path(s) could not be linked{check.OFF}")
        return 1
    print(f"{check.GREEN}✔ done{check.OFF}" if not dry else
          f"{check.GREEN}✔ dry run — nothing written{check.OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
