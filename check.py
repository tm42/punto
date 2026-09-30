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


# ── Sections ─────────────────────────────────────────────────


def check_links():
    say("links")
    for pkg in packages():
        counts = {}
        examples = {}
        for rel in managed(pkg):
            src, dst = PKGROOT / pkg / rel, HOME / rel
            if dst.is_symlink():
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
                try:
                    same = src.read_bytes() == dst.read_bytes()
                except OSError:
                    pass
                st = "real file, same content" if same else "real file, DIFFERENT content"
            counts[st] = counts.get(st, 0) + 1
            examples.setdefault(st, str(rel))

        if set(counts) == {"linked"}:
            ok(f"{pkg}: {counts['linked']} linked")
        else:
            detail = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
            bad(f"{pkg}: {detail}")
            for st, first in sorted(examples.items()):
                if st != "linked":
                    print(f"      e.g. {first}  — {st}")

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
