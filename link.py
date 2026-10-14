#!/usr/bin/env python3
"""Install this repo's dotfiles into $HOME and report what it did.

    ./link.py [--dry-run] [--prune]

The sibling of check.py's `links` section, and deliberately the only half that
writes. check.py already walks every package and sorts every managed path into
the states a path in $HOME can be in — seven if it is linked, six if it is
wrapped; this file is one policy per state plus the write, importing that walk
rather than restating it. A file added to a package is therefore linked here and
reported as missing there with no table to update in either program.

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
from check import (HEALTHY, HOME, PKGROOT, REPO, WRAPPABLE, managed, packages,
                   stale_links, wrap_state, wrapped_paths, wrapper_block,
                   wrapper_span)

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
#
# A path this machine has listed in ~/.config/punto/wrap is a real file punto
# co-owns, so it has six states of its own and the write is a block rather than a
# symlink:
#
#   wrapped                            nothing
#   missing                            write the block as the whole file
#   symlink where a wrapper belongs    replace it, printing the old target
#   real file, not wrapped             back up, then write the block
#   wrapper needs repair               splice the block in, keeping the rest
#   wrapper markers unusable           refuse, naming the way out
#
# The splice is the one that matters: the premise of wrapping is that something
# else writes this file too, so punto has to be able to repair its own block
# without destroying lines it did not write.
#
# Removing a path from that file un-wraps it with no policy of its own: it
# becomes an ordinary managed path, the wrapper is a real file whose content
# differs, and `different content` above backs it up and restores the symlink.
# check_links has one more verdict for that file — `wrapper nothing declares`,
# which names the cause rather than calling it a stray dotfile — and there is
# deliberately no entry for it here, because it is the same state as
# `different content` and the action above is already right.


def classify(src: Path, dst: Path, rel: Path, wrapped: set) -> str:
    """What `dst` is, relative to the repo file `src` that should own it.

    The same verdicts check_links reports, by the same tests, so the two
    programs cannot disagree about a path. The tests for a linked path are
    restated here rather than imported, because check_links prints as it goes
    and returns nothing. A wrapped path is not restated: it calls check.py's
    wrap_state outright, because the marker search and the byte comparison are
    the one thing both programs have to mean identically and are too easy to
    write twice slightly differently.

    `wrapped` is passed in rather than read here, because the file says what this
    machine wraps and reading it once per path would be 32 reads whose answers
    have to agree."""
    if str(rel) in wrapped and str(rel) in WRAPPABLE:
        return wrap_state(src, dst)[0]
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


def plan(wrapped: set) -> tuple[list, list]:
    """(actions, refusals) over every managed path in every package.

    An action is (verdict, pkg, rel). A refusal is (rel, why) — the message
    rather than the cause, because there are two causes now and one of them is
    not a path. Both refusals name the file, change nothing, and print in the
    dry run as well, which is what makes them a plan line rather than an error.

    HEALTHY rather than a second `!= "linked"` literal: a wrapped path that is
    already correct has to be as absent from this list as a correct symlink is,
    or the block is rewritten on every run, every dry run names it, and
    `every managed file is in place` below is never printed because `actions` is
    never empty."""
    actions, refused = [], []
    for pkg in packages():
        for rel in managed(pkg):
            blocker = symlinked_parent(rel)
            if blocker is not None:
                refused.append((rel, f"parent {blocker} is a symlink; move or "
                                     "remove it and re-run"))
                continue
            verdict = classify(PKGROOT / pkg / rel, HOME / rel, rel, wrapped)
            if verdict == "wrapper markers unusable":
                # Splicing against a missing or second close marker is the one
                # operation here that could swallow lines nobody has a copy of,
                # and a file another program appends to can grow a second marker
                # without anyone doing anything wrong — so the refusal needs a
                # way out and not only a message.
                refused.append((rel, "its punto markers are not exactly one "
                                     "well-formed pair; move it to "
                                     f"{check.tilde(BACKUP_ROOT)}/<timestamp>/ "
                                     "by hand and run again"))
            elif verdict not in HEALTHY:
                actions.append((verdict, pkg, rel))
    return actions, refused


# The verdicts that mean an existing symlink is about to be replaced. Where it
# pointed is printed on the plan line for each of these, so --dry-run says it too
# — it is the only record of the old target, nothing backs a symlink up, and a
# link into another checkout is the case where the right answer is to stop and
# read that repository first. INSTALL.md's preflight step sends the reader here
# for exactly that.
REPLACES_A_LINK = ("wrong file in this repo", "outside this repo",
                   "broken link", "symlink where a wrapper belongs")


def do_wrap(src: Path, dst: Path, rel: Path, verdict: str, stamp: str) -> None:
    """Make `dst` a real file holding punto's block.

    The block is the only part of the file punto writes, and a file whose block
    is already right never reaches here, so `punto link` run twice over a file
    something else has appended to does nothing the second time.

    The repair is read-modify-write, and that is the one case punto can destroy
    something it promised to keep: a write landing between the read and the
    write is overwritten by content derived from a snapshot taken before it, and
    nothing reports the loss. Writing through a temporary file and a rename does
    not fix that — it makes punto's overwrite atomic rather than avoiding it,
    and it discards a rename the other program may itself be doing. The
    assumption is recorded in the contract."""
    block = wrapper_block(src)
    if verdict == "wrapper needs repair":
        data = dst.read_bytes()
        lines = data.split(b"\n")
        _, open_i, close_i = wrapper_span(lines)
        # Every line outside the block back byte for byte, its own line endings
        # and all. Those lines are not punto's to normalise, and zsh only has to
        # parse the ones it executes.
        spliced = (lines[:open_i] + block.split(b"\n")[:-1]
                   + lines[close_i + 1:])
        dst.write_bytes(b"\n".join(spliced))
        return
    if verdict == "real file, not wrapped":
        # The same reversible move a real file at a linked path gets, and taken
        # whether or not it matches anything: there is no "identical" case for a
        # file punto did not write.
        bk = BACKUP_ROOT / stamp / rel
        bk.parent.mkdir(parents=True, exist_ok=True)
        dst.rename(bk)
        print(f"  saved   {rel}  ->  {check.tilde(bk)}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.write_bytes(block)


def do_link(pkg: str, rel: Path, verdict: str, stamp: str, wrapped: set) -> None:
    src, dst = PKGROOT / pkg / rel, HOME / rel
    if str(rel) in wrapped and str(rel) in WRAPPABLE:
        do_wrap(src, dst, rel, verdict, stamp)
        return
    if verdict == "different content":
        bk = BACKUP_ROOT / stamp / rel
        bk.parent.mkdir(parents=True, exist_ok=True)
        dst.rename(bk)
        print(f"  saved   {rel}  ->  {check.tilde(bk)}")
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

    wrapped, wrap_error = wrapped_paths()
    if wrap_error:
        # Before plan() and so before any write. Treating an unreadable list as
        # empty would un-wrap the machine on this very run: every wrapped path
        # would classify as a real file that differs, and the loop below would
        # back the wrapper up and restore the symlink. See check.wrapped_paths.
        print(f"cannot read the wrap list — {wrap_error}", file=sys.stderr)
        return 1

    actions, refused = plan(wrapped)
    stale = stale_links()

    check.say("link" + ("  (dry run — nothing is written)" if dry else ""))
    if not actions and not refused:
        check.ok(f"every managed file is in place  ({sum(len(managed(p)) for p in packages())} files)")
    for verdict, pkg, rel in actions:
        # readlink(), not resolve(): a broken link's target does not exist, and
        # what the reader needs is the path as written, not a path resolved
        # against a directory that may also be gone.
        was = (f"  (was -> {(HOME / rel).readlink()})"
               if verdict in REPLACES_A_LINK else "")
        act = ("wrap" if str(rel) in wrapped and str(rel) in WRAPPABLE
               else "link")
        print(f"  {'would ' + act if dry else act + '  '}  {rel}  ({verdict}){was}")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    failed = 0
    if not dry:
        for verdict, pkg, rel in actions:
            try:
                do_link(pkg, rel, verdict, stamp, wrapped)
            except OSError as e:
                check.bad(f"{rel}: {e}")
                failed += 1
    for rel, why in refused:
        # Named rather than skipped silently: the file stays as it is until the
        # cause is dealt with, and nothing else would ever say so.
        check.warn(f"{rel}: refused — {why}")

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
