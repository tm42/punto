#!/usr/bin/env python3
"""debug — which link in the agent-notification chain just broke?

MUTATES. Unlike check.py, this one creates a throwaway tmux window, sets pane
options, temporarily appends to status-right, and swaps a symlink. Every one of
those is undone before it exits — including on an exception or Ctrl-C — except
`tap on`, which is the one subcommand meant to leave a change in place until
`tap off` runs. `inspect` is the exception in the other direction: it only ever
reads, which is what makes it the safe thing to point at a pane that is stuck
right now. Running status-tick.sh by hand, as `chain` does, would sweep the very
notice you are trying to look at.

The chain it inspects, in order: an agent (Claude, Codex, opencode) fires a
hook -> ~/.tmux/agent-notify.sh sets @agent_state and four @notice_* pane
options -> ~/.tmux/status-tick.sh reads those on every status-right redraw and
renders the bar. Neither script is changed here — this walks it and drives it.

Stdlib only, Python 3.9, the same floor as check.py. Shells out to tmux, zsh
and jq rather than reimplementing any of them: the thing under test is the
real scripts, so a second implementation of their logic would pass while they
fail.

    ./debug.py wiring [--agent A] [--project DIR]  # read-only: is anything wired at all?
    ./debug.py inspect [WINDOW]              # read-only: why does that tab say that?
    ./debug.py chain [--agent claude|codex|opencode] [--target WINDOW]
    ./debug.py watch [--interval SECONDS] [--log PATH]
    ./debug.py mark [--log PATH] [TEXT ...]
    ./debug.py tap on|off|status
    ./debug.py --socket NAME <subcommand>   # talk to a different tmux server;
                                            # must come before the subcommand,
                                            # same placement as tmux's own -L.
                                            # For testing against a scratch
                                            # server instead of the one three
                                            # live agents depend on.

Logs land in ~/punto-debug/ — one directory to name in a sentence and delete
in one command. Not inside this checkout: punto is a public repo, and these
logs can carry the text of your prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
HOME = Path.home()
NOTIFY_LINK = HOME / ".tmux" / "agent-notify.sh"
STATUS_TICK_LINK = HOME / ".tmux" / "status-tick.sh"
REAL_NOTIFY = REPO / "dotfiles" / "tmux" / ".tmux" / "agent-notify.sh"
REAL_STATUS_TICK = REPO / "dotfiles" / "tmux" / ".tmux" / "status-tick.sh"

LOGDIR = HOME / "punto-debug"
WATCH_LOG = LOGDIR / "watch.log"
TAP_LOG = LOGDIR / "tap.log"
WRAPPER_PATH = LOGDIR / "agent-notify-tap.sh"

BOLD, DIM, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    BOLD = DIM = GREEN = YELLOW = RED = OFF = ""

_fail = 0
SOCKET = None  # set from --socket before any subcommand runs


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


def tmux(*args, env=None, input=None) -> subprocess.CompletedProcess:
    """Every tmux call goes through here so --socket only has to be threaded
    once. check=False throughout: a failing tmux command is itself the
    diagnostic, not a bug in this script, so callers branch on returncode."""
    cmd = ["tmux"]
    if SOCKET:
        cmd += ["-L", SOCKET]
    cmd += list(args)
    return subprocess.run(cmd, env=env, input=input, capture_output=True, text=True)


class ProbeFailed(Exception):
    """A probe could not be set up. Raised rather than returned so the caller's
    `finally` still tears down whatever was already created."""


# Everything status-tick.sh touches. It is not scoped to one pane — it sweeps
# `list-panes -a` — so these are what has to be put back afterwards.
SWEPT = ("@agent_state", "@notice_txt", "@notice_name", "@notice_glyph",
         "@notice_at", "@agent_screen", "@agent_screen_at")


# Separators for every `list-panes -F` read in this file. Not "|" and not a
# newline, which is what a tmux format is usually joined and split on, because
# both occur in the data: @notice_txt and @notice_name carry text an agent
# wrote. Measured, both on a scratch server:
#   a "|" in @notice_txt shifted every field after it one place left, and the
#     restore then wrote a non-numeric string into @notice_at on a real pane —
#     which status-tick.sh evaluates arithmetically on every redraw;
#   a newline in @notice_txt ended the record early, so the fields after it read
#     as unset and `inspect` reported, in detail, a fault that had not happened.
# Neither byte can appear in tmux's own output for these formats.
US, RS = "\x1f", "\x1e"


def panes_format(*fields: str) -> str:
    """A `list-panes -F` format that can be parsed back unambiguously."""
    return US.join("#{" + f + "}" for f in fields) + RS


def panes_rows(stdout: str, n: int) -> list:
    """The records of such a read, each one exactly n fields.

    Raises rather than padding or dropping. A short record used to be padded
    with empty strings, and empty is a meaningful value here — it is what an
    unset option looks like — so the padding did not read as missing data, it
    read as a pane whose notice had been cleared."""
    rows = []
    for record in stdout.split(RS):
        record = record.strip("\n")
        if not record:
            continue
        vals = record.split(US)
        if len(vals) != n:
            raise ProbeFailed(f"tmux returned {len(vals)} fields where {n} were "
                              f"asked for: {record!r}")
        rows.append(vals)
    return rows


def owned_options(*pane_ids: str) -> dict:
    """The user options each pane holds itself, as a set of names per pane.

    A `#{@opt}` format walks pane, window, session, global, so it cannot say
    whether the value it returned came from this pane. One `set -g` of a
    notification name is therefore a value on every pane at once rather than a
    stale value in one place, and every read below has to know the difference.

    `show -p` lists only the pane's own options. One call per pane, not one per
    option per pane: `show -pv <name>` would be seven calls each here and would
    replace the single delimiter-safe `list-panes` read as well. Only the name
    is parsed — the token before the first space — because `show -p` shell-quotes
    its values and nothing here needs them.

    A pane owning none prints nothing and exits 0. A pane that has gone exits
    non-zero and gets an empty set, which every caller reads as owning nothing,
    and that is what a vanished pane should look like."""
    out = {}
    for pane_id in pane_ids:
        r = tmux("show", "-p", "-t", pane_id)
        names = set()
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                name = line.split(" ", 1)[0]
                if name:
                    names.add(name)
        out[pane_id] = names
    return out


def own(field: str, value: str, owned: set) -> str:
    """`value` if this pane holds the option itself, "" if it does not.

    Only a `@`-prefixed user option can be inherited from a wider scope, so
    every other field in these reads is a pane property and passes through. So
    does an `E:`-prefixed one: @tab, @agent_lbl, @agent_is and @agent_name are
    set with `set -g` in .tmux.conf by design, because they are format templates
    meant to expand per pane, and scoping them would empty the tab report.

    "" is what every caller here already treats as no value. snapshot_options
    needs set-and-empty told apart from never-set and does its own mapping to
    None for that; nothing else does, because nothing else puts a value back."""
    if not field.startswith("@"):
        return value
    return value if field in owned else ""


def snapshot_options() -> dict:
    """Every pane's swept options, keyed by pane id.

    An option the pane does not hold itself is None rather than "", because the
    two have to be put back differently: "" is set-and-empty and is restored
    with `set -p`, None was never set and is restored with `set -pu`. A format
    returns "" for both and the global's value for neither, so the distinction
    can only be made here.

    Empty on any failure, including a record it cannot parse: restore_options
    is called from a `finally`, and a raise there would replace whatever sent
    the probe there in the first place."""
    r = tmux("list-panes", "-a", "-F", panes_format("pane_id", *SWEPT))
    if r.returncode != 0:
        return {}
    try:
        rows = panes_rows(r.stdout, len(SWEPT) + 1)
    except ProbeFailed:
        return {}
    owned = owned_options(*(row[0] for row in rows))
    return {row[0]: [val if name in owned[row[0]] else None
                     for name, val in zip(SWEPT, row[1:])]
            for row in rows}


def restore_options(before: dict, skip: str) -> int:
    """Put back anything the sweep changed on a pane that is not the probe.

    Running the real status-tick.sh is the whole point of the probe — a second
    implementation of its logic would pass while it fails. But it clears every
    pane whose notice is older than its HOLD, and on the machine you are
    debugging the sweep is the thing that is not running, so those notices have
    been piling up and are the evidence `watch` exists to collect. Undoing the
    collateral leaves the reading intact and the evidence where it was.

    An option that was never set is unset rather than set to "", because tmux
    tells the two apart: `show -pv` prints the empty value for one and exits 1
    for the other. A `#{@opt}` format cannot, which is why snapshot_options
    resolves it with `show -p` and records the never-set case as None.

    Reading through a format alone got both failing cases wrong, and neither
    looked like a failure. A pane whose own value happened to equal a global of
    the same name read identically before and after, so `was == now` skipped it
    and the sweep's clear was never undone. A pane whose own value was the empty
    string read as "" before and as the global's value after, so the restore
    fired but `if was:` was false and unset an option that had been set."""
    after = snapshot_options()
    restored = 0
    for pane_id, old_vals in before.items():
        if pane_id == skip or pane_id not in after:
            continue
        for name, was, now in zip(SWEPT, old_vals, after[pane_id]):
            if was == now:
                continue
            if was is None:
                tmux("set", "-pu", "-t", pane_id, name)
            else:
                tmux("set", "-p", "-t", pane_id, name, was)
            restored += 1
    return restored


def tmux_env_for_pane(pane_id: str) -> dict:
    """agent-notify.sh and status-tick.sh call bare `tmux`, not this script's
    -L-aware wrapper — they run on the machine being debugged, unmodified, so
    they resolve their server the way tmux always does: from $TMUX. Building
    that value here is what lets --socket reach a scratch server at all."""
    r = tmux("display", "-p", "-t", pane_id, "#{socket_path}|#{pid}|#{session_id}")
    parts = r.stdout.strip().split("|")
    if r.returncode != 0 or len(parts) != 3:
        raise ProbeFailed(f"could not read the server address for {pane_id}: "
                          f"{r.stderr.strip() or r.stdout.strip() or 'no output'}")
    sock_path, pid, sess_id = parts
    env = dict(os.environ)
    env["TMUX"] = f"{sock_path},{pid},{sess_id.lstrip('$')}"
    env["TMUX_PANE"] = pane_id
    return env


# ── chain ────────────────────────────────────────────────────


def pick_session():
    """Returns (session_id, caveat). caveat is None when a client is attached
    to the session chosen — only then does session_attached read nonzero and
    the foreground test in step 5 mean anything. Prefers an attached session
    over guessing; refuses to pick among several unattached ones, because a
    wrong guess there produces readings that look valid and are not.

    The id ($0) and not the name, because `-t <name>` is ambiguous: tmux reads
    a target that looks like a number as a window index in the current session.
    A session named "0" — which is what `tmux new-session` gives you when you
    never name one — turned `new-window -t 0` into "create window failed:
    index 0 in use". A session id can never be read as an index.

    session_attached is a count of clients, not a flag, so it is compared
    against "0" rather than against "1": a session you are attached to from
    two terminals reads 2, and testing for "1" dropped it."""
    r = tmux("list-sessions", "-F", "#{session_id}|#{session_attached}")
    if r.returncode != 0:
        return None, r.stderr.strip() or "no tmux server on this socket"
    rows = [ln.split("|") for ln in r.stdout.splitlines() if ln]
    if not rows:
        return None, "no sessions on this socket"
    attached = [sid for sid, att in rows if att != "0"]
    if attached:
        return attached[0], None
    if len(rows) == 1:
        return rows[0][0], "no client is attached — session_attached will read 0, so the background test below cannot mean anything"
    return None, f"{len(rows)} sessions on this socket, none with a client attached — re-run with an attached client, or reduce to one session"


def resolve_target_pane(target: str) -> str:
    """A window or pane the caller named — "3", "0:3", "%12", "3.1" — down to
    one pane id. tmux resolves it, not this function, so anything tmux accepts
    works and nothing here has to know the syntax. The first pane of a window
    with several is the one probed, and the caller prints what it resolved to
    so a target that landed somewhere unintended is visible rather than silent."""
    r = tmux("list-panes", "-t", target, "-F", "#{pane_id}")
    if r.returncode != 0 or not r.stdout.strip():
        raise ProbeFailed(f"--target {target!r}: {r.stderr.strip() or 'matched no pane'}")
    return r.stdout.split()[0]


def run_probe(session: str, event: str, message: str, agent: str, expect_state: str,
              expect_notice: bool, why_no_notice: str = "", target: str = None) -> None:
    """One throwaway window, one synthetic hook payload, one comparison that
    matters: whether status-tick.sh's own rendering agrees with what
    agent-notify.sh just set. Reporting the two readings separately — as an
    earlier version of this did — let a genuinely empty sweep pass silently
    whenever the notice was also, correctly, empty; the comparison is what
    catches an empty sweep sitting next to a notice that WAS set, which is
    the actual fault this tool exists to find. Torn down before returning, so
    two probes in the same chain() run never see each other's notice."""
    say(f"probe: {event} as {agent}")
    # window_id is bound before the try and the kill is guarded on it, so a
    # signal delivered between `new-window` returning and the try being entered
    # cannot leave the window behind. That gap is microscopic and it is also
    # the only one: current.toml makes "no throwaway window survives an
    # interrupt" a property, and a property with a hole in it is not one.
    window_id = None
    borrowed = None      # (pane_id, options as they were) when --target lent us one
    try:
        if target:
            # A window you already have and are willing to have written on, for
            # the case where creating one is what fails. Its options go back the
            # way `finally` puts a created window back: killed there, restored
            # here, and the probe itself is identical either way.
            pane_id = resolve_target_pane(target)
            where = tmux("display", "-p", "-t", pane_id,
                         "#{session_name}:#{window_index}.#{pane_index} #{pane_current_command}")
            ok(f"probing in {where.stdout.strip()} ({pane_id}), lent by --target {target}")
            borrowed = (pane_id, snapshot_options().get(pane_id))
        else:
            # -a, and the session by id: without -a tmux wants the target
            # window's own index, which is by definition in use.
            r = tmux("new-window", "-d", "-a", "-t", f"{session}:", "-P", "-F", "#{window_id}")
            if r.returncode != 0:
                bad(f"could not create a probe window: {r.stderr.strip()} — "
                    f"if a window is easier to lend than to create, ./debug.py chain --target <window>")
                return
            window_id = r.stdout.strip()
            r = tmux("list-panes", "-t", window_id, "-F", "#{pane_id}")
            pane_id = r.stdout.strip().splitlines()[0]

        r = tmux("display", "-p", "-t", pane_id,
                  "#{session_attached}|#{pane_active}|#{window_active}")
        sess_att, pane_act, win_act = r.stdout.strip().split("|")
        print(f"  session_attached={sess_att}  pane_active={pane_act}  window_active={win_act}")
        bg = sess_att == "1" and pane_act == "1" and win_act == "0"
        if bg:
            ok("probe pane is in the background — the readings below mean what they say")
        else:
            bad("probe pane is NOT in the background — the readings below are meaningless, "
                "not just wrong (see the run instructions for attaching a client on a scratch socket)")

        env = tmux_env_for_pane(pane_id)
        payload = json.dumps({"hook_event_name": event, "message": message,
                               "cwd": f"/debug-chain-probe-{agent}"})
        r = subprocess.run(["zsh", str(REAL_NOTIFY), agent],
                            input=payload, capture_output=True, text=True, env=env)
        if r.returncode != 0:
            bad(f"agent-notify.sh exited {r.returncode}: {r.stderr.strip()}")

        # Same two reasons as every other read in this file. The separators,
        # because @notice_txt carries the message the agent wrote and a "|" in
        # it shifted every field after it one place left. And the scope,
        # because the fault this block exists to catch — @notice_txt set with
        # @notice_at empty, from the `\;` chain in agent-notify.sh dying
        # between them — cannot fire while a global @notice_at makes nat read
        # non-empty on a pane that has none.
        fields = ("@agent_state", "@notice_txt", "@notice_name",
                  "@notice_glyph", "@notice_at")
        r = tmux("display", "-p", "-t", pane_id, panes_format(*fields))
        row = panes_rows(r.stdout, len(fields))[0]
        mine = owned_options(pane_id)[pane_id]
        state, ntxt, nname, nglyph, nat = [own(f, v, mine)
                                           for f, v in zip(fields, row)]
        print(f"  @agent_state={state!r}  @notice_txt={ntxt!r}  @notice_name={nname!r}  "
              f"@notice_glyph={nglyph!r}  @notice_at={nat!r}")
        ok(f"@agent_state={state}") if state == expect_state else \
            bad(f"@agent_state={state!r}, expected {expect_state!r}")

        if ntxt and not nat:
            bad("@notice_txt is set and @notice_at is empty — the \\; chain in agent-notify.sh "
                "died partway through (it sets txt first and at last), so something between "
                "those two `tmux set` calls is erroring")
            notice_set = False
        elif ntxt and nat:
            notice_set = True
            ok(f"notice set: {ntxt!r}") if expect_notice else \
                bad("a notice WAS set, and this event was not supposed to raise one for this agent — "
                    "the suppression in agent-notify.sh's case block is not firing")
        else:
            notice_set = False
            if expect_notice:
                bad("no notice was set — check the foreground test above; if it says background, "
                    "the fault is between the case-block glyph and the `if [[ $fg == 0 ]]` block")
            else:
                ok(f"no notice set{why_no_notice}")

        before = snapshot_options()
        r = subprocess.run(["zsh", str(REAL_STATUS_TICK)], capture_output=True, text=True,
                            env=tmux_env_for_pane(pane_id))
        restored = restore_options(before, skip=pane_id)
        if restored:
            warn(f"status-tick.sh swept {restored} option(s) on other panes; put back. "
                 "That is the sweep doing its job — on a machine where it is NOT running, "
                 "those notices are the evidence, which is why they are restored")
        print(f"  status-tick.sh stdout: {r.stdout!r}")
        if r.stderr.strip():
            print(f"  status-tick.sh stderr: {r.stderr.strip()}")
        tick_empty = not r.stdout.strip()
        if notice_set and tick_empty:
            bad("status-tick.sh printed nothing even though a notice was set — "
                "the notifier set the options and the sweep did not render them")
        elif notice_set:
            ok("status-tick.sh renders it")
        elif not tick_empty:
            bad("status-tick.sh printed something even though no notice was set")
    except ProbeFailed as e:
        bad(str(e))
    finally:
        if window_id:
            tmux("kill-window", "-t", window_id)
        elif borrowed and borrowed[1] is not None:
            restore_options({borrowed[0]: borrowed[1]}, skip=None)


def cmd_chain(args) -> int:
    say(f"chain — probing as agent={args.agent}" + (f" on socket {SOCKET}" if SOCKET else ""))

    # 1. symlinks resolve into this checkout
    for link, real in ((NOTIFY_LINK, REAL_NOTIFY), (STATUS_TICK_LINK, REAL_STATUS_TICK)):
        if not link.is_symlink():
            bad(f"{link} is not a symlink — run ./check.py links repo")
            continue
        try:
            resolved = link.resolve()
        except OSError:
            bad(f"{link} is a broken symlink")
            continue
        if resolved == real.resolve():
            ok(f"{link} -> checkout")
        else:
            warn(f"{link} -> {resolved}, not the checkout's {real} — "
                 "expected if `tap on` is running; ./debug.py tap status says")

    # 2. zsh -n against this machine's zsh
    zv = subprocess.run(["zsh", "--version"], capture_output=True, text=True)
    ok(f"zsh: {zv.stdout.strip() or zv.stderr.strip()}")
    for script in (REAL_NOTIFY, REAL_STATUS_TICK):
        r = subprocess.run(["zsh", "-n", str(script)], capture_output=True, text=True)
        ok(f"{script.name}: parses") if r.returncode == 0 else \
            bad(f"{script.name}: {r.stderr.strip()}")

    # 3. jq, tmux
    ok("jq present") if shutil.which("jq") else bad("jq missing — every event handler shells out to it")
    if not shutil.which("tmux"):
        bad("tmux missing — nothing past this line can run")
        return 1
    tv = tmux("-V")
    ok(f"tmux: {tv.stdout.strip()}") if tv.returncode == 0 else bad(f"tmux -V failed: {tv.stderr.strip()}")

    # 4. .tmux.conf actually sourced into the running server
    r = tmux("show", "-gv", "@agent_is")
    if r.returncode != 0 or not r.stdout.strip():
        bad("@agent_is is unset — .tmux.conf was never sourced into this server "
            "(a pull changes the file, not the running server; `tmux source-file ~/.tmux.conf`)")
        return 1
    ok(f"@agent_is set ({len(r.stdout.strip())} chars) — .tmux.conf is loaded")

    # 5. throwaway window, and whether it is genuinely in the background —
    # everything from here on is meaningless if this is wrong, so it is
    # checked and reported before anything that depends on it. With --target
    # there is no window to create and no session to guess: the caller named
    # the pane, and picking a session for it could only contradict them.
    session = None
    if not args.target:
        session, caveat = pick_session()
        if session is None:
            bad(f"no session to probe: {caveat}")
            return 1
        if caveat:
            warn(caveat)

    # 6/7. Two probes, not one. PermissionRequest first: every agent sets
    # state=wait and raises a ◆ notice for it with no branch on $agent, so it
    # exercises the notice link and the sweep regardless of --agent — this is
    # the probe that must catch "the notifier set the options and the sweep
    # printed nothing", which was the actual reported fault and which a
    # claude-only Notification probe cannot see, because agent-notify.sh
    # suppresses Notification's own glyph for claude and an empty sweep
    # reading is then indistinguishable from a healthy one.
    #
    # Notification second, as --agent: the one event whose glyph depends on
    # the agent (claude gets none, codex/opencode get one), so it is what
    # actually exercises the --agent flag — worth keeping, just not as the
    # only reading the default run depends on.
    run_probe(session, "PermissionRequest", "debug.py chain probe",
              args.agent, "wait", expect_notice=True, target=args.target)
    run_probe(session, "Notification", "debug.py chain probe",
              args.agent, "ready", expect_notice=(args.agent != "claude"),
              why_no_notice=" (expected: agent-notify.sh suppresses claude's own soft-ready glyph)",
              target=args.target)

    # 8. #() jobs actually run on status-right at all. #{E:status-right}
    # cannot answer this — it returns the format with job output missing,
    # which reads exactly like an empty bar. A marker file is the only way.
    say("status-right #() jobs")
    LOGDIR.mkdir(parents=True, exist_ok=True)
    marker = LOGDIR / f"chain-marker-{os.getpid()}"
    old_sr = tmux("show", "-gv", "status-right").stdout.rstrip("\n")
    try:
        # Inside the try, not before it, for the reason in run_probe: the finally
        # restores status-right to old_sr, and doing that when the set never
        # happened costs one tmux call and closes the interrupt window.
        tmux("set", "-g", "status-right", old_sr + f"#(touch {shlex.quote(str(marker))})")
        r = tmux("show", "-gv", "status-interval")
        try:
            interval = int(r.stdout.strip())
        except ValueError:
            interval = 15
        deadline = time.time() + interval * 2 + 3
        while time.time() < deadline and not marker.exists():
            time.sleep(0.3)
        if marker.exists():
            ok(f"marker appeared — #() jobs are running (status-interval={interval}s)")
        else:
            bad(f"marker never appeared within {interval * 2 + 3}s — #() jobs are not running "
                "(commonly: no client attached to redraw the bar)")
    finally:
        tmux("set", "-g", "status-right", old_sr)
        marker.unlink(missing_ok=True)

    print()
    if _fail:
        print(f"{RED}✘ {_fail} problem(s) above{OFF}")
    else:
        print(f"{GREEN}✔ the whole chain is alive{OFF}")
    return 1 if _fail else 0


# ── inspect ──────────────────────────────────────────────────

# status-tick.sh's own thresholds, read out of it rather than copied here: two
# files that have to agree about a number are two files that drift.
def tick_constant(name: str, default: int) -> int:
    try:
        for line in REAL_STATUS_TICK.read_text().splitlines():
            m = re.match(rf"\s*{name}=(\d+)", line)
            if m:
                return int(m.group(1))
    except OSError:
        pass
    return default


INSPECT_FIELDS = ("pane_id", "session_name", "window_index", "pane_index",
                  "pane_current_command", "pane_title", "window_active",
                  "pane_active", "session_attached", "@agent_state",
                  "@notice_txt", "@notice_name", "@notice_glyph", "@notice_at",
                  "@agent_screen_at", "E:@agent_lbl", "E:@tab", "E:@agent_is")


def read_panes(target=None) -> list:
    """Every field the tab is built from, for one target or for every pane.

    Three expansions, and the difference between them is the point.
    window-status-format draws #{E:@tab}, so that and nothing else is what the
    tab shows. @tab renders @agent_lbl only inside #{?#{E:@agent_is},...},
    while @agent_lbl itself is unguarded and expands on every pane — including
    a plain shell holding a stale @agent_state. Reading tmux's own expansions
    rather than reimplementing .tmux.conf's conditionals is what stops the
    report disagreeing with the screen; reading all three is what stops it
    calling a label a tab.

    The raw @-fields are scoped to the pane that holds them, so one global
    @notice_at does not report a notice on every pane at once. The E: fields
    are not scoped and must not be: they are the three expansions above."""
    args = ["list-panes", "-F", panes_format(*INSPECT_FIELDS)] + \
           (["-t", target] if target else ["-a"])
    r = tmux(*args)
    if r.returncode != 0:
        raise ProbeFailed(f"{target or 'every pane'}: {r.stderr.strip() or 'tmux list-panes failed'}")
    rows = [dict(zip(INSPECT_FIELDS, row))
            for row in panes_rows(r.stdout, len(INSPECT_FIELDS))]
    owned = owned_options(*(p["pane_id"] for p in rows))
    return [{f: own(f, v, owned[p["pane_id"]]) for f, v in p.items()}
            for p in rows]


def diagnose(pane: dict, now: int, hold: int, freeze: int) -> list:
    """What is stuck, and what would unstick it. One entry per finding, and no
    entry at all for a pane that is behaving — a report that says something
    about every pane is one nobody reads to the end of."""
    out = []
    state, title = pane["@agent_state"], pane["pane_title"]
    label, nat, pid = pane["E:@agent_lbl"], pane["@notice_at"], pane["pane_id"]
    # @agent_lbl expands on every pane; @tab draws it only inside
    # #{?#{E:@agent_is},...}. So @agent_is decides two things at once — whether
    # the label is on screen, and whether any process is left to fire the hook
    # that would clear the state behind it.
    alive, tab = pane["E:@agent_is"] == "1", pane["E:@tab"]

    if label.startswith("Action Required"):
        if state == "wait" and alive:
            out.append(
                "the tab says Action Required because @agent_state is wait. Nothing retires a "
                f"wait on a timer — status-tick.sh retires a frozen `working` after FREEZE={freeze}s "
                "and nothing else. The agent is still running in this pane, so it clears when it "
                "next fires UserPromptSubmit (you submit a prompt) or Stop (a turn ends). Do not "
                "clear it by hand: while the agent is alive, a wait is a prompt waiting for you.")
        elif state == "wait":
            out.append(
                f"@agent_state is wait on a pane running {pane['pane_current_command']!r}, which "
                "@agent_is does not match, so no agent is left here to fire the hook that would "
                f"clear it. The tab is NOT showing this — it reads {tab!r} — but @agent_lbl still "
                "expands to Action Required and pane-border-format draws that. "
                f"`tmux set -pu -t {pid} @agent_state` is what is left.")
        elif re.match(r"^[^|]*Action Required \|", title) and alive:
            out.append(
                f"the tab says Action Required because the pane TITLE does, and @agent_state is "
                f"{state!r}. Codex writes its run state into its own title, so punto is relaying "
                "it and keeps relaying it until the agent rewrites it. Nothing in this repo "
                "clears that, and nothing in this repo set it.")
        elif re.match(r"^[^|]*Action Required \|", title):
            out.append(
                f"the pane TITLE says Action Required and @agent_state is {state!r}, but @agent_is "
                f"does not match {pane['pane_current_command']!r}, so the tab is not relaying it — "
                f"it reads {tab!r}. The title is what the agent left behind when it exited. Nothing "
                "in this repo set it and nothing clears it but a new process writing a new title.")
        else:
            out.append("@agent_lbl expands to Action Required and neither @agent_state nor the "
                       "pane title explains it — read @agent_lbl in .tmux.conf")

    if pane["@notice_txt"] and not nat:
        out.append(
            "@notice_txt is set with @notice_at empty. The `\\;` chain in agent-notify.sh died "
            "between the two set calls — txt is set first and at is set last. status-tick.sh "
            "now clears this pair within one tick rather than skipping it, so this is a snapshot "
            "that may already have missed it by the time you read it.")
    elif nat.isdigit():
        age = now - int(nat)
        if age >= hold:
            out.append(
                f"the notice is {age}s old and still set, past HOLD={hold}s. The sweep is not "
                "clearing it: either no client is redrawing status-right, or status-tick.sh is "
                "failing. `./debug.py chain` separates those two.")

    if state == "working" and pane["@agent_screen_at"].isdigit():
        age = now - int(pane["@agent_screen_at"])
        if age >= freeze:
            out.append(f"state is working and the screen last changed {age}s ago, past "
                       f"FREEZE={freeze}s — the sweep should have retired it and has not.")
    return out


def cmd_inspect(args) -> int:
    """Read-only. Nothing here sets, unsets or sweeps anything, so it can be
    pointed at a pane that is misbehaving right now without destroying the
    evidence — which running status-tick.sh by hand would do."""
    now = int(time.time())
    hold, freeze = tick_constant("HOLD", 30), tick_constant("FREEZE", 30)

    # Everything below reads @tab, @agent_lbl and @agent_is, and tmux expands an
    # option that was never set to the empty string rather than failing. So on a
    # server .tmux.conf never reached, every tab would read as blank and every
    # pane as "no agent running here" — a confident wrong answer, which is the
    # one thing this module exists not to produce. `chain` makes the same check
    # for the same reason.
    r = tmux("show", "-gv", "@agent_is")
    if r.returncode != 0 or not r.stdout.strip():
        bad("@agent_is is unset — .tmux.conf was never sourced into this server, so nothing "
            "here draws a tab and nothing can be read as one. Every reading below would be "
            "of an option that does not exist. `tmux source-file ~/.tmux.conf` first.")
        return 1

    try:
        panes = read_panes(args.target)
    except ProbeFailed as e:
        bad(str(e))
        return 1

    # With a target the caller named the pane, so every pane of it is printed
    # even when clean — "nothing is set here" is the answer to half the
    # questions this command gets asked. Without one, only panes carrying
    # something, or the tab would be a list of every shell you have open.
    interesting = [p for p in panes
                   if args.target or p["@agent_state"] or p["@notice_at"] or p["@notice_txt"]
                   or p["E:@agent_lbl"].startswith(("Ready |", "Working |", "Action Required |"))]
    say(f"inspect — {len(interesting)} of {len(panes)} pane(s)"
        + (f" under {args.target}" if args.target else " carrying agent state")
        + (f" on socket {SOCKET}" if SOCKET else ""))
    if not interesting:
        print("  nothing set on any pane: no agent has reported into this server since it started.")
        return 0

    findings = 0
    for pane in interesting:
        fg = (pane["session_attached"] != "0" and pane["pane_active"] == "1"
              and pane["window_active"] == "1")
        print(f"\n{BOLD}{pane['session_name']}:{pane['window_index']}.{pane['pane_index']}{OFF}"
              f"  {pane['pane_id']}  {pane['pane_current_command']}"
              f"  {'foreground' if fg else 'background'}")
        print(f"  tab shows    : {pane['E:@tab']!r}")
        print(f"  @agent_lbl   : {pane['E:@agent_lbl']!r}"
              + ("" if pane["E:@agent_is"] == "1" else
                 f"   {DIM}(not on the tab: @agent_is does not match "
                 f"{pane['pane_current_command']!r}){OFF}"))
        print(f"  @agent_state : {pane['@agent_state']!r}")
        nat = pane["@notice_at"]
        age = f"{now - int(nat)}s ago" if nat.isdigit() else f"{nat!r}"
        print(f"  notice       : glyph={pane['@notice_glyph']!r} name={pane['@notice_name']!r} "
              f"at={age}")
        print(f"                 txt={pane['@notice_txt']!r}")
        print(f"  pane_title   : {pane['pane_title']!r}")
        for line in diagnose(pane, now, hold, freeze):
            findings += 1
            warn(line)

    print()
    if findings:
        print(f"{YELLOW}{findings} thing(s) to explain above{OFF}")
    else:
        ok("every pane above is in a state something will clear")
    return 0


# ── watch / mark ─────────────────────────────────────────────


def cmd_watch(args) -> int:
    log_path = args.log or WATCH_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"watching every pane's @agent_state / @notice_* every {args.interval}s -> {log_path}")
    print("Ctrl-C to stop. Never calls status-tick.sh: sweeping on its own schedule "
          "would clear the very notices this is trying to catch failing to clear.")
    try:
        with log_path.open("a") as f:
            while True:
                ts = int(time.time())
                sample = ("pane_id", "@agent_state", "@notice_txt",
                          "@notice_name", "@notice_glyph", "@notice_at")
                r = tmux("list-panes", "-a", "-F", panes_format(*sample))
                if r.returncode == 0:
                    try:
                        raw = panes_rows(r.stdout, len(sample))
                    except ProbeFailed as e:
                        # A sampler that dies on one bad tick loses the hours of
                        # recording it was left running for.
                        f.write(f"{ts}\tUNPARSED\t{e}\n")
                        f.flush()
                        time.sleep(args.interval)
                        continue
                    # Scoped to the pane that owns each option: a log read by
                    # someone who does not have the machine in front of them
                    # would otherwise carry one global as every pane's value.
                    owned = owned_options(*(row[0] for row in raw))
                    rows = [[own(fld, v, owned[row[0]])
                             for fld, v in zip(sample, row)] for row in raw]
                    for pane_id, state, ntxt, nname, nglyph, nat in rows:
                        # Only panes with something set: a full sweep every tick
                        # for every idle pane would drown the one line that matters.
                        # ntxt is in the test and not redundant — @notice_txt set
                        # while @notice_at is empty is the exact fault run_probe
                        # names, from the `\;` chain in agent-notify.sh dying
                        # between the two, and testing state and nat alone drops
                        # precisely the pane worth catching.
                        if state or nat or ntxt:
                            # Newlines escaped for the tap wrapper's reason: one
                            # event is one line, or grepping the log at the
                            # moment it matters is worth nothing.
                            ntxt = ntxt.replace("\n", "\\n")
                            f.write(f"{ts}\tSAMPLE\t{pane_id}\tstate={state}\tnotice_at={nat}\t"
                                    f"notice_txt={ntxt}\tnotice_name={nname}\tnotice_glyph={nglyph}\n")
                    f.flush()
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


def cmd_mark(args) -> int:
    log_path = args.log or WATCH_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = " ".join(args.text)
    ts = int(time.time())
    with log_path.open("a") as f:
        f.write(f"{ts}\tMARK\t{text}\n")
    print(f"marked {log_path} at {ts}" + (f": {text}" if text else ""))
    return 0


# ── tap ──────────────────────────────────────────────────────


def current_link_target():
    """None means missing or not a symlink. A dangling symlink instead comes
    back as its own (nonexistent) target — Path.resolve() doesn't raise for
    one — and every caller already rejects a target that isn't REAL_NOTIFY or
    WRAPPER_PATH, which a dangling link never is either."""
    if not NOTIFY_LINK.is_symlink():
        return None
    try:
        return NOTIFY_LINK.resolve()
    except OSError:
        return None


def write_wrapper():
    real = REAL_NOTIFY.resolve()
    lines = [
        "#!/bin/zsh",
        "# generated by debug.py tap on — do not edit by hand.",
        "# ~/.tmux/agent-notify.sh symlinks here while the tap runs;",
        f"# `./debug.py tap off` points it back at {real}.",
        "emulate -L zsh",
        "agent=${1:-claude}",
        "payload=$(cat)",
        "ts=$(date +%s)",
        "pane=${TMUX_PANE:-}",
        "# One line per event, newline escaped: Claude's .message carries the",
        "# text of your prompt, and a pretty-printed payload already arrives",
        "# split across lines — a log read by eye or by grep at the moment it",
        "# matters is worth nothing if one record spans several lines.",
        r"esc=${payload//$'\n'/\\n}",
        'print -r -- "$ts\t$agent\t$pane\t$esc" >> ' + shlex.quote(str(TAP_LOG)),
        'print -r -- "$payload" | exec ' + shlex.quote(str(real)) + ' "$agent"',
        "",
    ]
    WRAPPER_PATH.write_text("\n".join(lines))
    WRAPPER_PATH.chmod(0o755)


def cmd_tap(args) -> int:
    LOGDIR.mkdir(parents=True, exist_ok=True)

    if args.action == "status":
        target = current_link_target()
        if target is None:
            bad(f"{NOTIFY_LINK} is not a symlink, or is broken — outside what tap manages; run ./check.py links repo")
            return 1
        if target == REAL_NOTIFY.resolve():
            print("tap off")
        elif target == WRAPPER_PATH.resolve():
            print(f"tap ON — logging to {TAP_LOG}")
        else:
            warn(f"{NOTIFY_LINK} points at {target}, which is neither the checkout nor the tap wrapper")
        return 0

    if args.action == "on":
        target = current_link_target()
        if target == WRAPPER_PATH.resolve():
            print("tap already on")
            return 0
        if target != REAL_NOTIFY.resolve():
            bad(f"{NOTIFY_LINK} does not currently point into the checkout ({target}) — "
                "refusing to tap over an already-broken link; run ./check.py links repo first")
            return 1
        print("tap on will start recording every event this script receives, including "
              "Claude's .message field — which carries the text of your prompt — to "
              f"{TAP_LOG}.")
        write_wrapper()
        NOTIFY_LINK.unlink()
        NOTIFY_LINK.symlink_to(WRAPPER_PATH)
        print(f"tap on — {NOTIFY_LINK} -> {WRAPPER_PATH}")
        return 0

    # off
    target = current_link_target()
    if target == REAL_NOTIFY.resolve():
        print("tap already off")
        return 0
    NOTIFY_LINK.unlink(missing_ok=True)
    NOTIFY_LINK.symlink_to(REAL_NOTIFY)
    print(f"tap off — {NOTIFY_LINK} -> {REAL_NOTIFY}")
    return 0


# ── wiring: has each agent been told to call the notifier at all? ─────────────

# What agent-notify.sh does with each event it handles. Not authoritative on its
# own: notify_case_events() below reads the script's own `case` arm labels and
# cmd_wiring reports a disagreement, so this table is caught being stale instead
# of being trusted after the notifier has moved on.
NOTIFY_EVENTS = {
    "PermissionRequest": "wait",
    "UserPromptSubmit": "working",
    "Stop": "ready",
    "Notification": "ready",   # soft — never overwrites a pending wait
}
STATES = ("wait", "working", "ready")

# `  PermissionRequest|Notification)` and `  Stop)  state=ready; ...` match;
# `  *)`, `  fi ;;` and every comment or continuation line inside the block do
# not, because none of them is a bare word immediately followed by `)`.
CASE_ARM = re.compile(r"^\s*([A-Za-z][A-Za-z|]*)\)")


def notify_case_events() -> set:
    """The event names agent-notify.sh's `case $event in` actually handles.

    Only the arm LABELS are readable this way. UserPromptSubmit and Stop set
    their state on the arm line, but PermissionRequest|Notification decides its
    state inside an if/else several lines down, so the event-to-state mapping
    stays in NOTIFY_EVENTS and this answers the narrower question of whether
    that table still names the same events the script does. An empty set means
    the file could not be read or the block was not found, which the caller
    reports rather than reading as "handles nothing"."""
    try:
        src = REAL_NOTIFY.read_text()
    except OSError:
        return set()
    body = src.partition("case $event in")[2].partition("esac")[0]
    events = set()
    for line in body.splitlines():
        m = CASE_ARM.match(line)
        if m:
            events.update(m.group(1).split("|"))
    return events


def hooks_from_json(path: Path):
    """(event, command) for every hook in a Claude- or Codex-shaped settings
    file. None if the file is absent; ValueError carrying the parse error if it
    will not parse; OSError propagates, because a file that cannot be read and
    a file that cannot be parsed are fixed by different things and the caller
    says which.

    The whole file is parsed, because JSON has no partial parse and these files
    can hold tokens. Nothing but hook events and hook commands is returned, so
    nothing else can reach the report."""
    if not path.exists():
        return None
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(str(e)) from None
    out = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks") or []:
                if isinstance(hook, dict):
                    out.append((str(event), str(hook.get("command", ""))))
    return out


def points_at_notifier(command: str) -> bool:
    """Whether a hook command runs ~/.tmux/agent-notify.sh. The path is written
    three different ways across the configs that exist today — `~/.tmux/...`,
    `$HOME/.tmux/...`, and an absolute path — so expand each token and compare,
    then fall back to the basename, which is the test a person reading the file
    applies."""
    try:
        tokens = shlex.split(command) if command else []
    except ValueError:            # an unbalanced quote is still a command a human can read
        tokens = command.split()
    for tok in tokens:
        expanded = os.path.expanduser(os.path.expandvars(tok))
        if expanded and Path(expanded) == NOTIFY_LINK:
            return True
    return "agent-notify.sh" in command


def tilde(p: Path) -> str:
    try:
        return "~/" + str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def claude_files(project: Path) -> list:
    """Claude reads hooks from the user's settings and the project's, each with
    a `.local` sibling. All four are named in the report whether or not they
    exist, because "absent" and "present but not wired" are different answers
    and a reader who cannot see which files were opened cannot tell them
    apart."""
    return [HOME / ".claude" / "settings.json",
            HOME / ".claude" / "settings.local.json",
            project / ".claude" / "settings.json",
            project / ".claude" / "settings.local.json"]


def report_json_agent(files: list) -> tuple:
    """Print one JSON-configured agent's wiring, file by file, and return the
    events bound to the notifier across all of them along with whether this
    agent is configured here at all.

    The second half of that pair is what stops the caller crying wolf: an agent
    nobody installed contributes no hooks, and so does an agent whose install
    half happened. Only the second is a fault."""
    wired, present = set(), False
    for path in files:
        link = f" -> {tilde(path.resolve())}" if path.is_symlink() else ""
        try:
            hooks = hooks_from_json(path)
        except OSError as e:
            present = True
            bad(f"{tilde(path)}{link} cannot be read: {e}")
            continue
        except ValueError as e:
            present = True
            bad(f"{tilde(path)}{link} does not parse: {e}. Every hook in it is lost, "
                "including any that are correct.")
            continue
        if hooks is None:
            # exists() follows symlinks, so a link into a checkout that is not
            # there lands here — the commonest wiring fault after "never
            # configured", and the one thing that tells them apart is the
            # arrow, which was computed a line ago.
            if path.is_symlink():
                present = True
                bad(f"{tilde(path)}{link} is a dangling symlink: nothing reads it, because "
                    "the target is not there. `./check.py links repo` says where punto "
                    "expects it.")
            else:
                print(f"    ·  {tilde(path)} — absent")
            continue
        present = True
        mine = sorted((e, c) for e, c in hooks if points_at_notifier(c))
        other = sorted({c for e, c in hooks if not points_at_notifier(c)})
        if mine:
            print(f"    {GREEN}✔{OFF}  {tilde(path)}{link}")
            for event, command in mine:
                wired.add(event)
                print(f"         {event:<18} {command}")
        elif hooks:
            print(f"    ·  {tilde(path)}{link} — {len(hooks)} hook(s), none reaching the notifier")
        else:
            print(f"    ·  {tilde(path)}{link} — no hooks declared")
        if other:
            print(f"       {DIM}also bound here: {', '.join(other)}{OFF}")
    return wired, present


def report_opencode() -> set:
    """opencode has no hooks file — the plugin's presence is the wiring — so the
    events it sends are read out of the strings it passes to its own notify().
    Measured from the file rather than listed here: a table of opencode's events
    in this repo would be a third copy of something already written twice."""
    plugdir = HOME / ".config" / "opencode" / "plugins"
    files = sorted(plugdir.glob("*.ts")) if plugdir.is_dir() else []
    if not files:
        print(f"    ·  {tilde(plugdir)} — no plugin file")
        return set(), False
    wired = set()
    for path in files:
        link = f" -> {tilde(path.resolve())}" if path.is_symlink() else ""
        try:
            src = path.read_text(errors="replace")
        except OSError as e:
            bad(f"{tilde(path)}{link} cannot be read: {e}")
            continue
        if "agent-notify.sh" not in src:
            print(f"    ·  {tilde(path)}{link} — does not mention the notifier")
            continue
        events = set(re.findall(r'notify\(\s*"(\w+)"', src))
        print(f"    {GREEN}✔{OFF}  {tilde(path)}{link}")
        print("         calls the notifier with: "
              + (", ".join(sorted(events)) if events else "no literal event name found in the source"))
        wired |= events
    return wired, True


def cmd_wiring(args) -> int:
    """Read-only, and the one subcommand that needs no tmux server: whether an
    agent was ever told to call the notifier is upstream of everything `chain`
    tests, and a chain that is alive end to end is still silent if nothing calls
    it. Reads configuration only — it cannot see whether a hook fires, which is
    what `tap` records."""
    project = Path(args.project).resolve() if args.project else Path.cwd()
    say(f"wiring — who calls {tilde(NOTIFY_LINK)}?  (project: {tilde(project)})")

    target = current_link_target()
    if target is None:
        bad(f"{tilde(NOTIFY_LINK)} is not a symlink, or is broken. Nothing calling that path "
            "runs at all; `./check.py links repo` says what punto expects there.")
    elif target == WRAPPER_PATH.resolve():
        warn(f"{tilde(NOTIFY_LINK)} points at the tap wrapper — `./debug.py tap off` puts it back.")
    else:
        ok(f"{tilde(NOTIFY_LINK)} -> {tilde(target)}")

    handled = notify_case_events()
    if not handled:
        warn(f"could not read the `case` arms out of {tilde(REAL_NOTIFY)}, so the event names "
             "below are this script's own table with nothing checking them.")
    else:
        stale = set(NOTIFY_EVENTS) ^ handled
        if stale:
            warn("debug.py's event table and agent-notify.sh disagree on "
                 + ", ".join(sorted(stale))
                 + ". The table is stale, so the states reported below are not to be trusted.")

    for agent in ([args.agent] if args.agent else ["claude", "codex", "opencode"]):
        print(f"\n  {BOLD}{agent}{OFF}")
        if agent == "claude":
            wired, present = report_json_agent(claude_files(project))
        elif agent == "codex":
            wired, present = report_json_agent([HOME / ".codex" / "hooks.json"])
        else:
            wired, present = report_opencode()

        if not wired and not present:
            # Two agents of the three are not installed on a typical machine.
            # Reporting that as a fault would make a non-zero exit the normal
            # case, and an exit code that is 1 on a healthy machine is one
            # nobody reads twice.
            print(f"       {DIM}not configured on this machine — nothing to wire.{OFF}")
            continue
        if not wired:
            bad(f"{agent} is configured here and none of it reaches the notifier, so its panes "
                "never get a state or a notice — every other link being healthy changes nothing.")
            continue
        reach = {NOTIFY_EVENTS[e] for e in wired if e in NOTIFY_EVENTS}
        print(f"       reaches: {', '.join(s for s in STATES if s in reach)}")
        missing = [s for s in STATES if s not in reach]
        if missing:
            print(f"       {DIM}not reachable: {', '.join(missing)} — nothing wired here maps "
                  f"to {'them' if len(missing) > 1 else 'it'}.{OFF}")
        unknown = sorted(e for e in wired if e not in NOTIFY_EVENTS)
        if unknown:
            print(f"       {DIM}also sent, with no arm in agent-notify.sh: {', '.join(unknown)} "
                  f"— these take its `*` fallthrough, which sets no state.{OFF}")

    print(f"\n{DIM}This reads configuration, not traffic: an agent that never sends an event "
          f"looks the same here as one that was never wired for it. `./debug.py tap on` "
          f"records what an agent actually sends.{OFF}")
    return 1 if _fail else 0


# ── entry point ──────────────────────────────────────────────


def main() -> int:
    global SOCKET
    p = argparse.ArgumentParser(
        prog="debug.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--socket", metavar="NAME",
                    help="tmux -L NAME — talk to a non-default server instead of the one "
                         "three live agents use. Must come before the subcommand.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_chain = sub.add_parser("chain", help="one-shot: is every link between a hook and the bar alive?")
    p_chain.add_argument("--agent", choices=("claude", "codex", "opencode"), default="claude")
    p_chain.add_argument("--target", metavar="WINDOW",
                         help="probe in a window you already have — anything tmux accepts as a "
                              "target: 3, sess:3, %%12. Its options are put back afterwards. Use it "
                              "when creating a window is what fails, or when you want the probe to "
                              "land somewhere you can watch.")

    p_wiring = sub.add_parser(
        "wiring", help="read-only: has each agent been told to call the notifier at all?")
    p_wiring.add_argument("--agent", choices=("claude", "codex", "opencode"),
                          help="just this one. Default: all three.")
    p_wiring.add_argument("--project", metavar="DIR",
                          help="the project whose .claude/settings*.json to read alongside the "
                               "home pair. Default: the current directory.")

    p_inspect = sub.add_parser("inspect",
                               help="read-only: what state is each pane in, and what is stuck?")
    p_inspect.add_argument("target", nargs="?", metavar="WINDOW",
                           help="one window or pane (3, sess:3, %%12). Omit for every pane "
                                "carrying agent state.")

    p_watch = sub.add_parser("watch", help="continuous sampler, for faults that will not reproduce on demand")
    p_watch.add_argument("--interval", type=float, default=2.0, metavar="SECONDS")
    p_watch.add_argument("--log", type=Path, metavar="PATH")

    p_mark = sub.add_parser("mark", help="record, from a second pane, the moment you saw a bad notice")
    p_mark.add_argument("--log", type=Path, metavar="PATH")
    p_mark.add_argument("text", nargs="*")

    p_tap = sub.add_parser("tap", help="log every agent-notify.sh invocation with its full payload")
    p_tap.add_argument("action", choices=("on", "off", "status"))

    args = p.parse_args()
    SOCKET = args.socket

    if args.cmd == "chain":
        return cmd_chain(args)
    if args.cmd == "wiring":
        return cmd_wiring(args)
    if args.cmd == "inspect":
        return cmd_inspect(args)
    if args.cmd == "watch":
        return cmd_watch(args)
    if args.cmd == "mark":
        return cmd_mark(args)
    return cmd_tap(args)


if __name__ == "__main__":
    sys.exit(main())
