#!/usr/bin/env python3
"""check — is this machine set up the way INSTALL.md describes?

READ-ONLY. This script opens files and runs read-only commands — `which`, `brew
list`, `git ls-files`, `gitleaks detect`. It creates nothing, writes
nothing, and deletes nothing — there is no code path here that modifies the
filesystem, which is the whole reason it is a program and the installing is not.

Installing is done by hand, following INSTALL.md. Checking that every symlink
actually resolves into this repo is the one part that is tedious enough to
automate and cannot hurt you if it is wrong.

Stdlib only, Python 3.9 — what macOS ships at /usr/bin/python3.

    ./check.py            check everything
    ./check.py links      just one section (links, tools, clones, machine,
                          claude, codex, opencode, repo)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PKGROOT = REPO / "dotfiles"
HOME = Path.home()
MACHINE = HOME / ".config" / "punto" / "machine.zsh"
STATUSLINE_LOCAL = HOME / ".config" / "punto" / "statusline.sh"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
CODEX_CONFIG = HOME / ".codex" / "config.toml"
OPENCODE_PLUGIN = HOME / ".config" / "opencode" / "plugins" / "tmux-agent.ts"

# Homebrew formulae the configs need. Formula → the command it provides, or None
# when it ships a shell source with no binary (checked under share/ instead).
TOOLS = {
    "tmux": "tmux",
    "neovim": "nvim",
    "fzf": "fzf",
    "zoxide": "zoxide",
    "bat": "bat",
    "jq": "jq",
    "ripgrep": "rg",
    "node": "node",          # mason installs pyright and ts_ls from npm
    "tree-sitter-cli": "tree-sitter",   # the `tree-sitter` formula is the library
                                        # neovim depends on and ships no binary
    "pre-commit": "pre-commit",
    "fzf-tab": None,
    "zsh-autosuggestions": None,
    "zsh-syntax-highlighting": None,
}

# Casks. Without a Nerd Font every powerline separator, the git branch glyph and
# every nvim devicon renders as tofu — the prompt and statusline stop matching,
# which is the first visible thing this setup claims.
FONT_CASKS = ["font-jetbrains-mono-nerd-font"]

CLONES = {
    ".oh-my-zsh": HOME / ".oh-my-zsh",
    "you-should-use": HOME / ".oh-my-zsh/custom/plugins/you-should-use",
    "zsh-bat": HOME / ".oh-my-zsh/custom/plugins/zsh-bat",
    "zsh-histdb": HOME / ".oh-my-zsh/custom/plugins/zsh-histdb",
    "tpm": HOME / ".tmux/plugins/tpm",
}
TPM_PLUGINS = ["tmux-sensible", "tmux-yank", "tmux-thumbs", "extrakto"]

# Paths in $HOME, relative to it, that punto is able to wrap rather than
# symlink — for a machine where something else rewrites them. ~/.zshrc is the
# one member: the work machine runs a security agent that watches it, adds its own
# lines, and adds them again when they are moved into ~/.zshrc.local, which
# cannot help because that file is sourced by the file being watched. Wrapped,
# the agent writes to a real file in $HOME and dotfiles/zsh/.zshrc is never the
# file it edits.
#
# Two separate questions, and they belong in two separate places. *What can be
# wrapped* is a property of the tracked file: punto's block is zsh, so the file
# has to be one a shell sources, and it has to resolve nothing against its own
# path, because after wrapping it is sourced rather than being the file zsh
# read. That is reviewed code and lives here. *Whether to wrap* is a property of
# one machine — only the machine running something that rewrites the file needs
# it — and lives in ~/.config/punto/wrap, which is untracked and per machine.
#
# Without the split, an entry naming .config/nvim/init.lua would be valid, link
# would replace the symlink with a six-line zsh block, nvim would not start, and
# check_links would print `nvim: 1 wrapped, 16 linked` and exit 0 — the checker
# calling a dead configuration healthy. 22 of the 32 managed paths are files no
# shell reads. Being a shell file is not enough either: cheat.sh derives its own
# directory from $0, which a wrapper would change.
WRAPPABLE = {".zshrc"}

WRAP_FILE = HOME / ".config" / "punto" / "wrap"

# The verdicts that mean nothing to do. Two tests share them — check_links'
# healthy line and link.py's plan() — and a verdict missing from either is a
# correct path reported as broken or rewritten on every run.
HEALTHY = ("linked", "wrapped")

STATUSLINE_CMD = "~/.claude/statusline-agnoster.sh"
NOTIFY_NAME = "agent-notify.sh"
# UserPromptSubmit is not for notifying — it is the only way to know Claude
# started, because its pane title never changes. See agent-notify.sh.
NOTIFY_EVENTS = ("UserPromptSubmit", "PermissionRequest", "Notification", "Stop")

BOLD, DIM, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    BOLD = DIM = GREEN = YELLOW = RED = OFF = ""

_fail = 0


def say(m):
    print(f"\n{BOLD}{m}{OFF}")


def ok(m):
    print(f"  {GREEN}✔{OFF} {m}")


def warn(m):
    print(f"  {YELLOW}!{OFF} {m}")


def bad(m):
    global _fail
    _fail += 1
    print(f"  {RED}✘{OFF} {m}")


def tilde(p) -> str:
    s = str(p)
    return "~" + s[len(str(HOME)):] if s.startswith(str(HOME)) else s


def brew_prefix():
    for p in ("/opt/homebrew", "/usr/local", "/home/linuxbrew/.linuxbrew"):
        if Path(p, "bin", "brew").is_file():
            return Path(p)
    return None


def packages():
    return sorted(p.name for p in PKGROOT.iterdir() if p.is_dir())


def managed(pkg):
    """Files a package owns. Skips OS and editor droppings, which are not config
    and would otherwise be reported as unlinked forever."""
    root = PKGROOT / pkg
    skip = {".DS_Store", "Thumbs.db"}
    return sorted(p.relative_to(root) for p in root.rglob("*")
                  if p.is_file() and p.name not in skip
                  and not p.name.endswith(("~", ".swp", ".swo", ".orig", ".rej")))


def stale_links() -> list:
    """Symlinks into this repo, in a directory a package owns, at a path no
    package owns any more.

    Nothing reported these before, so a dotfile deleted from a package left a
    dangling link in $HOME for good — managed() and the old loop both iterate
    over files that are *currently* in the repo, and check_repo does not sweep
    $HOME from the other direction either.

    The comparison is against the union of every package's managed set, never
    one package's. $HOME itself is a directory three packages populate — docs
    (.nvimcheatsheet.md, .tmux-quickstart.md), tmux (.tmux.conf) and zsh
    (.zshrc) — so a per-package comparison would call ~/.tmux.conf stale while
    looking at zsh, and --prune would delete it.

    Bounded to the directories those paths live in, so it never walks $HOME as a
    whole."""
    owned, dirs = set(), set()
    for pkg in packages():
        for rel in managed(pkg):
            owned.add(rel)
            dirs.add(rel.parent)
    stale = []
    for d in sorted(dirs):
        try:
            entries = sorted((HOME / d).iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            try:
                target = entry.resolve()
            except OSError:
                # A dangling link into the repo cannot be resolved, so read the
                # target as written; a relative one is resolved against its own
                # directory the way the filesystem would.
                target = Path(entry.readlink())
                if not target.is_absolute():
                    target = (entry.parent / target).resolve(strict=False)
            if REPO not in target.parents and target != REPO:
                continue
            rel = d / entry.name
            if rel not in owned:
                stale.append((rel, target))
    return stale


# ── A wrapped path, which punto co-owns with whatever else writes it ────────

WRAP_OPEN = b"# >>> punto >>>"
WRAP_CLOSE = b"# <<< punto <<<"


def wrapper_block(src: Path) -> bytes:
    """The exact bytes of punto's block in a wrapped file, for the package file
    `src` the block has to source.

    The one piece of generated text in this repository, and it is generated
    because the checkout's absolute path is machine-specific. link.py writes
    what this returns and never a second copy of the text, and check_links
    compares against what this returns, so the program that writes a block and
    the program that validates one cannot disagree about it.

    Hardcoding the path rather than sourcing a punto-owned symlink keeps the
    only symlink in a directory no package owns out of the picture —
    stale_links bounds its scan to directories a package owns, so a dangling one
    at ~/.config/punto/ would be reported by nothing."""
    return b"\n".join([
        WRAP_OPEN,
        b"# punto owns these six lines and nothing else in this file.",
        b"# The configuration is the file sourced below - edit it there.",
        b"# Machine-local lines go in ~/.zshrc.local, which that file sources.",
        b'source "' + os.fsencode(src) + b'"',
        WRAP_CLOSE,
    ]) + b"\n"


def wrapped_paths() -> tuple:
    """(paths, error): which paths this machine wraps instead of linking, read
    from ~/.config/punto/wrap, and why the file could not be read.

    One $HOME-relative path per line. Blank lines and lines whose first non-space
    character is # are skipped, so the file can carry the sentence that explains
    it to whoever opens it next. Absent is not an error and means wrap nothing —
    that is the default and the state a machine is in until someone writes the
    file.

    Returns the failure rather than raising it. main() calls each section bare,
    so an exception here would end `./check.py links repo` in a traceback and
    take the `repo` section down along with `links`.

    A file that is present and unreadable is a failure and not an empty set.
    Falling back to wrapping nothing would silently un-wrap the machine, and
    un-wrapping is not inert: the next `punto link` would find a real file whose
    content differs, back the wrapper up and restore the symlink, handing the
    other program the repository copy again. That is the failure the wrapper
    exists to prevent, reached because one read of a twenty-byte file failed."""
    try:
        text = WRAP_FILE.read_text()
    except FileNotFoundError:
        return set(), None
    except OSError as e:
        return set(), f"{tilde(WRAP_FILE)}: {e}"
    paths = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        paths.add(line.strip())
    return paths, None


def _strip_cr(line: bytes) -> bytes:
    """One trailing \\r, removed. Not rstrip: a line ending \\r\\r was not
    produced by converting line endings and is not a marker."""
    return line[:-1] if line.endswith(b"\r") else line


def wrapper_span(lines: list) -> tuple:
    """Where punto's block is in `lines`: ("found", open, close), ("absent",
    -1, -1) when the file holds no marker at all, or ("unusable", -1, -1) when
    the markers are not exactly one well-formed pair — unterminated,
    duplicated, or closed before it opens.

    One trailing \\r is stripped here and nowhere else. A wrapper whose endings
    have been converted to CRLF sources nothing: \\r is not whitespace to zsh's
    lexer, so it becomes the last character of the path and the file is not
    found — measured on zsh 5.9, exit 127. Such a file therefore has to be
    recognised as a wrapper so that it can be repaired. Stripping on the block
    comparison as well would make it compare clean and leave nothing that could
    ever reach the repair."""
    opens = [i for i, ln in enumerate(lines) if _strip_cr(ln) == WRAP_OPEN]
    closes = [i for i, ln in enumerate(lines) if _strip_cr(ln) == WRAP_CLOSE]
    if not opens and not closes:
        return "absent", -1, -1
    if len(opens) != 1 or len(closes) != 1 or opens[0] > closes[0]:
        return "unusable", -1, -1
    return "found", opens[0], closes[0]


def wrap_state(src: Path, dst: Path) -> tuple:
    """What the wrapped path `dst` is relative to the package file `src`, and
    how many of its lines lie outside punto's block.

    Six verdicts, and link.py has one policy per verdict: `wrapped`, `wrapper
    needs repair`, `wrapper markers unusable`, `missing`, `symlink where a
    wrapper belongs`, and `real file, not wrapped`. check_links has one more that
    is not here, because it belongs to a path this machine has *not* listed:
    `wrapper nothing declares`.

    Bytes throughout, and nothing here decodes a line punto did not write.
    `read_text` would be worse than untidy: a UnicodeDecodeError is a
    ValueError, so the read's `except OSError` would not catch it, nothing else
    would either — main() calls each section bare — and one non-UTF-8 byte that
    another program put in ~/.zshrc would end `./check.py links repo` in a
    traceback, taking the `repo` section down along with `links`.

    The count is the number of lines of the file punto does not own, and it is
    the only place that fact is visible at all. It is a reading rather than an
    alarm: nothing stores what it was last time, so on a machine where another
    program's lines arrive on the first day it is non-zero for ever. It is 0 for
    every verdict but `wrapped`, where the rest of the file has not been
    established to be intact."""
    if dst.is_symlink():
        return "symlink where a wrapper belongs", 0
    if not dst.exists():
        return "missing", 0
    try:
        data = dst.read_bytes()
    except OSError:
        # Unreadable is treated as foreign, the way an unreadable real file at a
        # linked path is treated as differing. link.py's backup of it then fails
        # for the same reason and says so.
        return "real file, not wrapped", 0
    lines = data.split(b"\n")
    where, open_i, close_i = wrapper_span(lines)
    if where == "absent":
        return "real file, not wrapped", 0
    if where == "unusable":
        return "wrapper markers unusable", 0
    # Exactly, with no \r stripped: see wrapper_span. The builder ends in a
    # newline, so the last element of its split is the empty string after it.
    if lines[open_i:close_i + 1] != wrapper_block(src).split(b"\n")[:-1]:
        return "wrapper needs repair", 0
    total = len(lines) - 1 if data.endswith(b"\n") else len(lines)
    return "wrapped", total - (close_i + 1 - open_i)


# ── Sections ─────────────────────────────────────────────────


def check_links():
    say("links")
    wrapped, wrap_error = wrapped_paths()
    if wrap_error:
        # Reported and the section stopped, rather than states this cannot know:
        # if the wrapped set is unknown then every path's verdict is unreliable,
        # not only the wrapped ones. See wrapped_paths.
        bad(f"cannot read the wrap list — {wrap_error}")
        return
    # An entry that names nothing wrappable wraps nothing, and nothing else here
    # would ever say so: the walk below iterates the packages, so a path no
    # package owns is simply never visited. A one-line file is where a typo is
    # least likely to be noticed, and the machine a typo leaves linked is the one
    # whose reason for wrapping has not gone away. The same test covers an
    # absolute path, a path with .. in it, a path deleted from a package since
    # the line was written, and a package-owned path a zsh block would break.
    for entry in sorted(wrapped - WRAPPABLE):
        bad(f"{tilde(WRAP_FILE)} lists {entry}, which punto cannot wrap; "
            f"wrappable: {', '.join(sorted(WRAPPABLE))}")
    for pkg in packages():
        counts = {}
        examples = {}
        notes = []
        for rel in managed(pkg):
            src, dst = PKGROOT / pkg / rel, HOME / rel
            if str(rel) in wrapped and str(rel) in WRAPPABLE:
                st, outside = wrap_state(src, dst)
                if outside:
                    notes.append(f"{rel}  — {outside} "
                                 f"line{'' if outside == 1 else 's'} outside "
                                 "punto's block, which punto does not own")
            elif dst.is_symlink():
                try:
                    resolved = dst.resolve()
                except OSError:
                    st = "broken link"
                else:
                    if resolved == src.resolve():
                        st = "linked"
                    elif REPO in resolved.parents:
                        st = "linked to the wrong file in this repo"
                    else:
                        st = "links outside this repo"
            elif not dst.exists():
                st = "missing"
            else:
                # A real file where a link should be. Two very different causes:
                # never installed, or a program replaced the link by writing a
                # new file over it — which silently detaches it from the repo.
                same = False
                data = None
                try:
                    data = dst.read_bytes()
                    same = src.read_bytes() == data
                except OSError:
                    pass
                if (not same and data is not None
                        and wrapper_span(data.split(b"\n"))[0] != "absent"):
                    # A wrapper this machine no longer declares. The action is
                    # the same either way — link backs it up and restores the
                    # symlink, which is what un-wrapping is — but the cause is
                    # not. ~/.config/punto/wrap is untracked, in no template and
                    # one line long, so a $HOME restore or a rebuilt machine can
                    # lose it with the wrapper still in place; reported as a
                    # differing real file, the remedy INSTALL.md gives is the
                    # conversion, which hands the other program the repository
                    # copy again. The markers are already located in this pass.
                    st = "wrapper nothing declares"
                else:
                    st = ("real file, same content" if same
                          else "real file, DIFFERENT content")
            counts[st] = counts.get(st, 0) + 1
            examples.setdefault(st, str(rel))

        detail = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        # HEALTHY and not {"linked"}: a correctly wrapped path is as healthy as
        # a correct symlink, and a package of nothing but wrapped files reports
        # `zsh: 1 wrapped`. `counts and` keeps a package holding no managed file
        # at all a fault rather than turning it into a pass.
        if counts and set(counts) <= set(HEALTHY):
            ok(f"{pkg}: {detail}")
        else:
            bad(f"{pkg}: {detail}")
            for st, first in sorted(examples.items()):
                if st not in HEALTHY:
                    print(f"      e.g. {first}  — {st}")
        # How much of a wrapped file punto does not own. The only place that is
        # visible at all, and a reading rather than an alarm: nothing stores
        # what it was last time, so where another program writes to the wrapper
        # it is non-zero for ever and sits on the passing line. What it replaces
        # is worse — that agent appending through a symlink put its lines in the
        # repository copy while the checker reported the package as healthy and
        # showed nothing at all.
        for note in notes:
            print(f"      {note}")

    # The other direction, which nothing here looked at before: a link into this
    # repo at a path the repo no longer has. The loop above walks the files that
    # are currently in a package, so a dotfile deleted from one left its symlink
    # in $HOME dangling and unreported for good.
    for rel, target in stale_links():
        warn(f"{tilde(HOME / rel)} -> {tilde(target)} — points into this repo at "
             "a path no package owns; ./link.py --prune deletes it")


def check_tools():
    say("tools")
    prefix = brew_prefix()
    if not prefix:
        warn("no Homebrew found — the three zsh plugins in .zshrc §7 cannot load")
    for formula, command in TOOLS.items():
        if command:
            ok(command) if shutil.which(command) else bad(f"{command} missing  (brew install {formula})")
        elif prefix and (prefix / "share" / formula).is_dir():
            ok(formula)
        else:
            bad(f"{formula} missing  (brew install {formula})")

    # Casks are not on PATH, so ask brew. If brew cannot answer, fall back to
    # looking for the files, and say which check was used rather than guessing.
    installed = ""
    if prefix:
        installed = subprocess.run([str(prefix / "bin" / "brew"), "list", "--cask"],
                                   capture_output=True, text=True).stdout
    for cask in FONT_CASKS:
        if cask in installed:
            ok(cask)
        elif list(Path(HOME / "Library" / "Fonts").glob("*Nerd*")) if (HOME / "Library" / "Fonts").is_dir() else False:
            warn(f"{cask} not installed, but a Nerd Font is present in ~/Library/Fonts")
        else:
            bad(f"{cask} missing  (brew install --cask {cask})"
                " — powerline separators and nvim icons will render as tofu")


def check_clones():
    say("third-party clones")
    for name, path in CLONES.items():
        # A .git directory, not just any directory: a failed clone can leave an
        # empty tree behind, and a bare is_dir() would call that success forever.
        if (path / ".git").is_dir():
            # Clean, not just present. oh-my-zsh updates itself with `git pull
            # --rebase` under rebase.autoStash, so an edit inside one of these
            # survives until upstream touches the same file and then lands as a
            # conflict — the prompt lived in a modified agnoster.zsh-theme until
            # 2026-09-01 and nothing said so.
            d = subprocess.run(["git", "-C", str(path), "status", "--porcelain",
                                "--untracked-files=no"], capture_output=True, text=True)
            ok(name) if not d.stdout.strip() else \
                warn(f"{name}: locally modified, and an update can conflict with it — "
                     + " ".join(line.split(maxsplit=1)[1]
                                 for line in d.stdout.strip().splitlines()))
        elif path.is_dir():
            bad(f"{name}: {tilde(path)} exists but is not a git clone — delete it and clone again")
        else:
            bad(f"{name} missing — see INSTALL.md step 3")
    for p in TPM_PLUGINS:
        path = HOME / ".tmux" / "plugins" / p
        ok(p) if path.is_dir() else warn(f"{p} missing — press C-a I inside tmux")
    lazy = HOME / ".local/share/nvim/lazy/lazy.nvim"
    ok("lazy.nvim") if lazy.is_dir() else warn("lazy.nvim missing — launch nvim once")


def check_machine():
    say("machine-specific")
    if not MACHINE.is_file():
        bad(f"{tilde(MACHINE)} absent — .zshrc §2 sources it; the project picker has no roots")
        return
    roots = []
    for line in MACHINE.read_text().splitlines():
        line = line.strip()
        if line.startswith("export TMUX_SESSIONIZER_ROOTS="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            roots = [os.path.expandvars(os.path.expanduser(r))
                     for r in value.split(":") if r]
    if not roots:
        warn("machine.zsh sets no TMUX_SESSIONIZER_ROOTS — M-o falls back to"
             " ~/projects ~/code ~/dev ~/src ~/work ~/repos")
        return
    # Check the directories, not the line. The shipped example already contains
    # the line, so testing for its presence passes on exactly the unedited state
    # this check exists to catch.
    live = [r for r in roots if Path(r).is_dir()]
    if live:
        ok(f"machine.zsh: {len(live)}/{len(roots)} roots exist ({', '.join(tilde(Path(r)) for r in live)})")
    else:
        bad(f"machine.zsh names roots that do not exist: {', '.join(roots)}"
            " — still the shipped example?")

    secrets = HOME / ".config/secrets/secrets.zsh"
    ok("secrets.zsh present") if secrets.is_file() else \
        warn("secrets.zsh absent (fine if this machine needs no API keys)")



def check_claude():
    say("Claude Code")
    if not CLAUDE_SETTINGS.is_file():
        warn(f"{tilde(CLAUDE_SETTINGS)} absent — see INSTALL.md step 7")
        return
    try:
        s = json.loads(CLAUDE_SETTINGS.read_text(errors="replace"))
    except json.JSONDecodeError as exc:
        bad(f"settings.json does not parse: {exc}")
        return
    if not isinstance(s, dict):
        bad("settings.json is not a JSON object")
        return

    # Optional, and its absence is the normal case — so this only ever says it is
    # there. Worth saying: the statusline sources it, so a bar carrying a segment
    # nothing in this repo explains has exactly one other source. Reported here
    # rather than in check_machine, which returns early on three paths.
    if STATUSLINE_LOCAL.is_file():
        ok(f"{tilde(STATUSLINE_LOCAL)} present — the statusline sources it")

    live = (s.get("statusLine") or {}).get("command")
    if live == STATUSLINE_CMD:
        ok("statusLine points at this repo's script")
    elif live:
        # Step 7 refuses to overwrite a statusline you configured yourself, so
        # this is a choice until proven otherwise — report it, do not fail on it.
        warn(f"statusLine is your own {live!r}, not {STATUSLINE_CMD!r}"
             " — INSTALL.md step 7 has the one-liner to switch")
    else:
        bad(f"no statusLine set — expected {STATUSLINE_CMD!r}  (INSTALL.md step 7)")

    def hook_cmds(event):
        return [str(h.get("command", ""))
                for entry in s.get("hooks", {}).get(event, []) or []
                for h in entry.get("hooks", []) or []]

    absent = [e for e in NOTIFY_EVENTS
              if not any(NOTIFY_NAME in c for c in hook_cmds(e))]
    if not absent:
        ok("notifier wired on " + ", ".join(NOTIFY_EVENTS))
    else:
        stale = [e for e in absent if any("claude-notify.sh" in c for c in hook_cmds(e))]
        bad("notifier missing on " + ", ".join(absent)
            + (" — still on the pre-rename claude-notify.sh; re-run INSTALL.md step 7"
               if stale else ""))


def check_codex():
    say("Codex")
    if not shutil.which("codex"):
        warn("codex not installed — skipping  (brew install --cask codex)")
        return

    if not CODEX_CONFIG.is_file():
        bad(f"{tilde(CODEX_CONFIG)} absent — see INSTALL.md step 8")
        return
    # errors="replace" because this file only ever gets read: a stray non-UTF-8
    # byte in it used to abort the whole run with a traceback and take every
    # later section down with it. terminal_title is ASCII, so a replacement
    # character cannot change a verdict.
    body = CODEX_CONFIG.read_text(errors="replace")

    # Checked first, and it returns: a duplicate table means Codex loads NO
    # config, so reporting on a terminal_title below it would tick a line Codex
    # is not reading. Matched per line, not counted as a substring — "[tui]" in
    # a comment, or a [projects."/x/[tui]/y"] trust key, is not a table.
    if len(re.findall(r"^\s*\[tui\]\s*$", body, re.M)) > 1:
        bad("two [tui] tables — a duplicate table makes Codex load no config at all")
        return

    # Not parsed as TOML: this has to run on the python3 macOS ships, and
    # tomllib arrived in 3.11. Only one line matters — but it matters WHERE it
    # is, so slice the [tui] table out first. A terminal_title in the root table
    # or under [projects."…"] is a key Codex never reads, and it is the exact
    # mistake INSTALL.md step 8 warns about.
    tui = re.search(r"^\s*\[tui\]\s*$(.*?)(?=^\s*\[|\Z)", body, re.M | re.S)
    if not tui:
        bad("no [tui] table — see INSTALL.md step 8")
        return

    # [^\[\]]*? and not .*? : an unclosed bracket used to run the match on into
    # the next table header, reporting a config Codex refuses to load as fine.
    m = re.search(r"^\s*terminal_title\s*=\s*\[([^\[\]]*?)\]", tui.group(1), re.M | re.S)
    if not m:
        bad("[tui] has no terminal_title — the tab shows Codex's raw pane title"
            " and no state word  (INSTALL.md step 8)")
        return

    items = [i.strip().strip('\'"') for i in m.group(1).split(",") if i.strip()]
    # @tab needs run-state to be the FIRST " | "-separated field, because it
    # reads that word. `activity` is exempt: it is a prefix rather than a field,
    # rendering "\u2826 " or "[ . ]" with no separator after it.
    fields = [i for i in items if i != "activity"]
    if fields[:1] == ["run-state"]:
        ok("terminal_title: " + " ".join(items))
    elif "run-state" in items:
        warn("run-state is not the first field in terminal_title: " + " ".join(items)
             + " \u2014 an earlier field displaces the state word and the tab shows"
             " the raw title")
    else:
        warn("terminal_title has no run-state: " + " ".join(items)
             + " \u2014 the tab can never say Action Required for Codex")


def check_opencode():
    say("opencode")
    if not shutil.which("opencode"):
        warn("opencode not installed — skipping  (brew install opencode)")
        return

    # There is no config file to get wrong here: a plugin runs because it is in
    # the directory, not because anything names it, and opencode asks for no
    # approval the way Codex does. So the link is check_links's and the only thing
    # left is whether the linked file still calls the notifier.
    #
    # The is_file() guard is not check_links twice over: `./check.py opencode`,
    # which INSTALL.md step 9 tells you to run, does not run check_links, and
    # read_text() below would raise without it.
    #
    # Matched on the assignment rather than anywhere in the file, because the
    # header comment names the script too — a plugin that had lost the live
    # `const NOTIFY` line still passed a plain substring test.
    if not OPENCODE_PLUGIN.is_file():
        bad(f"{tilde(OPENCODE_PLUGIN)} absent — see INSTALL.md step 9")
    elif re.search(rf"^const NOTIFY\s*=.*{re.escape(NOTIFY_NAME)}",
                   OPENCODE_PLUGIN.read_text(errors="replace"), re.M):
        ok(f"plugin calls {NOTIFY_NAME}")
    else:
        bad(f"{tilde(OPENCODE_PLUGIN)} has no `const NOTIFY` naming {NOTIFY_NAME}"
            " — opencode then sets no state and raises no notice")


def check_repo():
    say("repo hygiene")
    r = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                       capture_output=True, text=True)
    if r.returncode:
        warn("not a git repo — skipping")
        return
    names = {"secrets.zsh", ".netrc", ".pypirc", "hosts.yml", "credentials",
             "rclone.conf", "settings.local.json", ".claude.json"}
    leaked = [t for t in r.stdout.split() if Path(t).name in names]
    bad("tracked credential file(s): " + " ".join(leaked)) if leaked else \
        ok("no known credential file is tracked")

    if shutil.which("gitleaks"):
        g = subprocess.run(["gitleaks", "detect", "--source", str(REPO),
                            "--no-banner", "--redact"], capture_output=True)
        ok("gitleaks: clean") if g.returncode == 0 else \
            bad("gitleaks found something — run: gitleaks detect --source . --redact")
    else:
        warn("gitleaks not installed — the pre-commit hook fetches it on demand")

    # git does not clone hooks, so a fresh clone has none and nothing says so.
    # This is the only place that notices.
    hook = REPO / ".git" / "hooks" / "pre-commit"
    ok("pre-commit hook installed") if hook.is_file() else \
        bad("no pre-commit hook — gitleaks never runs  (cd " + tilde(REPO)
            + " && pre-commit install)")


SECTIONS = {
    "links": check_links,
    "tools": check_tools,
    "clones": check_clones,
    "machine": check_machine,
    "claude": check_claude,
    "codex": check_codex,
    "opencode": check_opencode,
    "repo": check_repo,
}


def main() -> int:
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        if name in ("-h", "--help"):
            print(__doc__)
            return 0
        if name not in SECTIONS:
            print(f"no such section: {name}\navailable: {', '.join(SECTIONS)}",
                  file=sys.stderr)
            return 2
    for name in wanted:
        SECTIONS[name]()
    print()
    if _fail:
        print(f"{RED}✘ {_fail} problem(s){OFF} — see INSTALL.md")
    else:
        print(f"{GREEN}✔ all good{OFF}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
