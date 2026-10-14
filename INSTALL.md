# Installing

Done by hand, by you or by an agent following this file. There is no installer, on
purpose: the install runs twice — once per machine — and after that `git pull` *is* the
update, because every file in `$HOME` is a symlink into this repo and is already live.
A program that runs twice and can delete your files is a bad trade.

Read each step before running it. Every command here is one you can inspect first.

Assumes macOS or Linux, Homebrew, and git. Steps 1–11 take about twenty minutes.

---

## 1. Clone

```sh
git clone https://github.com/tm42/punto ~/punto
cd ~/punto
```

Anywhere works; `~/punto` is assumed below. The clone must stay where you put it —
the symlinks point at it, so moving it later breaks every one of them.

## 2. Install the tools

```sh
brew install tmux neovim fzf fzf-tab zsh-autosuggestions zsh-syntax-highlighting \
             zoxide bat jq ripgrep node tree-sitter-cli pre-commit
brew install --cask font-jetbrains-mono-nerd-font
```

You also need a C compiler and `make`, which nvim shells out to. Both come with Xcode
Command Line Tools on macOS, which Homebrew already required, so a Mac that can run the
line above has them. On Linux, install `build-essential` (or your distribution's
equivalent). Check:

```sh
for t in cc make tree-sitter; do
  command -v "$t" >/dev/null && echo "ok   $t" || echo "FAIL $t"
done
```

Three of those are easy to skip and all three matter:

- **The font is not optional.** The prompt separators, the Claude statusline arrows, the
  git branch glyph and every nvim file icon are Private Use Area characters. Without a
  Nerd Font they render as empty boxes. **Then set your terminal to use it** — installing
  it is not enough.
- **`node`** is there because nvim's mason installs `pyright` and `typescript-language-server`
  from npm. Without it those two silently fail while the other two language servers work,
  which is more confusing than all four failing.
- **`tree-sitter-cli`, not `tree-sitter`.** The `tree-sitter` formula is the library, and
  brew installs it anyway as a neovim dependency — it ships no binary. `nvim-treesitter`
  shells out to the CLI to build each parser, so without this formula `python`, `bash`,
  `json`, `yaml` and `toml` fall back to vim's regex highlighting and nvim says so once
  per launch. `pre-commit` is for step 10.

## 3. Clone the third-party pieces

Not vendored — other people's repos on their own release cadence.

```sh
git clone --depth 1 https://github.com/ohmyzsh/ohmyzsh.git ~/.oh-my-zsh
git clone --depth 1 https://github.com/MichaelAquilina/zsh-you-should-use.git \
    ~/.oh-my-zsh/custom/plugins/you-should-use
git clone --depth 1 https://github.com/fdellwing/zsh-bat.git \
    ~/.oh-my-zsh/custom/plugins/zsh-bat
git clone --depth 1 https://github.com/larkery/zsh-histdb.git \
    ~/.oh-my-zsh/custom/plugins/zsh-histdb
git clone --depth 1 https://github.com/tmux-plugins/tpm.git ~/.tmux/plugins/tpm
```

**Check each one succeeded.** A failed clone can leave an empty directory behind, which
then looks installed forever after. Verify:

```sh
for d in ~/.oh-my-zsh ~/.oh-my-zsh/custom/plugins/you-should-use \
         ~/.oh-my-zsh/custom/plugins/zsh-bat ~/.oh-my-zsh/custom/plugins/zsh-histdb \
         ~/.tmux/plugins/tpm; do
  [ -d "$d/.git" ] && echo "ok   $d" || echo "FAIL $d"
done
```

zsh-histdb also needs `sqlite3` on PATH. macOS already has it at /usr/bin/sqlite3; a
Linux machine needs it installed separately.

lazy.nvim is deliberately absent — `init.lua` fetches it on first launch.

## 4. See what is in the way

This prints what the link step would touch. It changes nothing.

```sh
cd ~/punto
./link.py --dry-run
```

Read the output before continuing.

One line per file that is not already in place, each ending in the reason. A file that is
already correct prints nothing, so on a second run an empty list is the whole report. The
verb is `would link` for every file that becomes a symlink, and `would wrap` for a path this
machine has listed in `~/.config/punto/wrap` — a real file holding a block of punto's own
instead of a symlink. On a machine that has not written that file, which is the default and
probably this one, no line says `wrap` and the five wrapped verdicts below cannot appear.

- `missing` — nothing there, the link is free.
- `same content` — a real file byte-for-byte identical to the repo copy. Replaced by the
  link and not saved anywhere, because there is nothing in it to lose. A path this machine
  has listed as wrapped never reports this: a real file there is `real file, not wrapped`
  whether it matches or not, and it is saved first either way.
- `different content` — a real file that differs. Step 5 moves it to
  `~/punto-backup/<timestamp>/` before linking, so your aliases survive; this is your chance
  to see which files that will be.
- `wrong file in this repo`, `outside this repo`, `broken link` — already a symlink, and each
  line names where it currently points. A symlink is not backed up, and that printed target
  is the only record of it — so **if it points into another repo, stop and look at that repo
  first.**
- `refused — parent … is a symlink` — a directory on the way to this file is a symlink into
  somewhere else, so writing the link would reach through it and replace a real file in that
  other checkout rather than touching `$HOME` at all. Testing the file itself cannot see
  this, because the test resolves the parent components first. Step 5 refuses these and names
  both the file and the parent; move or remove the parent symlink and re-run it to pick the
  file up.

The five below belong to a path this machine has listed in `~/.config/punto/wrap`:

- `symlink where a wrapper belongs` — the path is still a symlink, which is what a machine
  prints on the first run after it lists the path. Replaced by the wrapper, and the line
  names the target it pointed at.
- `real file, not wrapped` — a real file with no punto block in it, which is what a machine
  that has never run these steps has. Moved to `~/punto-backup/<timestamp>/` first — whether
  or not it matches the repo copy, because there is no "identical" case for a file punto did
  not write — and then the wrapper is written.
- `wrapper needs repair` — a punto block that is not the block punto would write now. Either
  the checkout moved, or the block's wording changed in the repo, or something converted the
  file to CRLF line endings, which stops the `source` line working at all and leaves the
  shell with none of its configuration. Step 5 splices the current block in and every line
  outside it survives byte for byte.
- `wrapper markers unusable` — the `# >>> punto >>>` and `# <<< punto <<<` markers are not
  exactly one well-formed pair: unterminated, duplicated, or closed before they open.
  Refused and left alone, because splicing against a missing or second marker is the one
  thing here that could swallow lines nobody has another copy of. Move the file to
  `~/punto-backup/<timestamp>/` by hand and run the step again.
- `wrapper nothing declares` — a real file holding punto's block at a path this machine has
  *not* listed. Either the line was removed on purpose, which is how a path is un-wrapped, or
  `~/.config/punto/wrap` went missing — it is untracked and one line long, so a restored or
  rebuilt `$HOME` can lose it. Step 5 treats it as any other real file that differs: moved to
  `~/punto-backup/<timestamp>/` and replaced by the symlink. If that is not what you meant,
  write the path back into the wrap file before running step 5.

Everything above is the same walk step 5 carries out — `--dry-run` is that step with the
writes switched off, not a second opinion about it.

## 5. Link

```sh
cd ~/punto
./link.py            # --dry-run first, if you want to see the plan
```

For every file in every package, make the matching path in `$HOME` point at the repo copy —
a symlink, unless this machine has listed the path in `~/.config/punto/wrap`, which the fourth
bullet below explains. Four things happen before each write, and each one is a way this step
used to be able to destroy something:

- **A real file whose content differs is moved aside first**, so `~/.tmux.conf` and whatever
  you had in it end up in `~/punto-backup/<timestamp>/.tmux.conf` rather than gone. The
  directory is created only when something is actually saved, and re-running the step makes
  no empty ones. A file identical to the repo copy is replaced with the link and not saved,
  because there is nothing in it to lose.
- **A symlinked parent is refused**, because replacing a link named as the target itself is
  safe and one in a parent is not. Without this test, a `~/.config/nvim` pointing at
  another checkout means the step replaces a file in *that* repo, outside `$HOME`.
- **An existing symlink is replaced and its old target printed.** Nothing is saved — the
  link is one line of output and that output is all you get, so read it.
- **A path listed in `~/.config/punto/wrap` is wrapped rather than linked**, because
  something else on that machine rewrites it and a symlink there means the rewrite lands in
  this repository. It becomes a real file holding one block between `# >>> punto >>>` and
  `# <<< punto <<<` whose single statement sources the repo copy from the checkout by absolute
  path. That block is the only part of the file punto writes or checks; every other line in
  it belongs to whatever put it there and is kept byte for byte, including lines another
  program adds, which is the whole reason for wrapping. The configuration is still the repo
  copy and that is the file to edit. No machine wraps anything until someone writes that
  file — the subsection below is the whole procedure.

Re-running is safe: an already-correct link is left alone and prints nothing, and so is an
already-correct wrapper — punto does not rewrite a block that is already right, so lines
something else appended to a wrapped file are never at risk on a re-run. Only the refusals
need action. A file refused for a symlinked parent stays unlinked until you clear the parent
and run the step again; a wrapped file refused for unusable markers stays as it is until you
move it to `~/punto-backup/<timestamp>/` by hand and run the step again, which you may have to
do without having done anything wrong, because a program that appends to that file can leave a
second marker behind.

`./link.py` also refuses the whole run, before writing anything, if `~/.config/punto/wrap`
exists and cannot be read. An unreadable list is not an empty one: treating it as empty would
un-wrap every path on it in that same run.

`./link.py` also names a symlink in one of these directories that points into the repo at a
path no package owns any more — what a dotfile deleted from a package leaves behind. It
reports those and never removes them; `./link.py --prune` is what deletes them, and it is
the only thing here that deletes anything in `$HOME`.

**Open a new shell before using `punto`.** This step is what puts `~/.local/bin/punto` on
disk, and `.zshrc` §1 decided whether to add `~/.local/bin` to `PATH` when *this* shell
started — so `punto` does not resolve until the next one. From then on `punto link` works
from any directory, and it is what to run after a pull that adds a file to a package: a
pull brings the file into the repo and creates no symlink for it.

Editing a linked file now edits the repo file. That is the point: `git diff` shows your
change immediately and there is no copy-back step to forget.

A wrapped path is the exception, and the cost of wrapping it: that path in `$HOME` is the
six-line wrapper, so the configuration to edit is the repo copy in the checkout —
`dotfiles/zsh/.zshrc` for `~/.zshrc`. `punto check links` reports it as `wrapped` rather than
`linked`, and tells you how many lines of the file are outside punto's block — how much of it
punto does not own. On a machine where another program writes there, that number is non-zero
for good and is a reading rather than a warning. Machine-local lines still go in
`~/.zshrc.local`, which the repo copy sources at the end.

### Something else on this machine keeps rewriting a file punto manages

A security agent, an MDM profile, a vendor installer — anything that opens a file in `$HOME`
and adds its own lines. If that path is a punto symlink, the write follows the link and lands
in `dotfiles/` inside the checkout, where it is a change to this repository: `git diff` shows
it, a push publishes it, and `punto check links` says `linked` the whole time, because the
symlink is intact and nothing looked at what came down it.

Wrapping is the answer, and it is per machine. Only the machine with that program needs it,
and nothing in the repo turns it on:

```sh
mkdir -p ~/.config/punto
printf '# Paths punto makes a real wrapper instead of a symlink,\n# because something else on this machine rewrites them.\n.zshrc\n' > ~/.config/punto/wrap
punto link --dry-run      # expect: would wrap  .zshrc  (symlink where a wrapper belongs)
punto link
```

Then open a new shell and run `punto check links`. The zsh line should read `zsh: 1 wrapped`,
followed by a count of the lines outside punto's block once the other program has written
again.

One path per line, `$HOME`-relative, no leading `~/` or `/`. Blank lines and `#` comments are
ignored. **Only `.zshrc` can be listed today**: punto's block is zsh — two comments and a
`source` line — so the file has to be one a shell reads, and it has to resolve nothing against
its own path, because after wrapping it is sourced rather than being the file zsh started
with. `dotfiles/zsh/.zshrc` qualifies; `init.lua` and a script that derives its own directory
from `$0` do not. An entry naming anything else is reported by `punto check links` as a path
punto cannot wrap, and nothing is wrapped.

To un-wrap, delete the line. The next `punto link` moves the wrapper to
`~/punto-backup/<timestamp>/` — the other program's lines with it — and restores the symlink.
Losing the file by accident does exactly the same thing, with one difference worth knowing:
`punto check links` reports that path as `wrapper nothing declares` rather than as a stray real
file, so the cause is on the screen before you run the step that acts on it.

## 6. Your machine's own values

```sh
mkdir -p ~/.config/punto
cp -n machine.zsh.example ~/.config/punto/machine.zsh   # -n: never clobber an edited one
$EDITOR ~/.config/punto/machine.zsh
```

**Set `TMUX_SESSIONIZER_ROOTS`** to where your projects actually live — the shipped value
is a guess and the project picker (`M-o`) is useless until it is right. The file is
gitignored and never committed; it and `~/.config/secrets/secrets.zsh` are where anything
machine-specific or secret belongs.

`~/.config/punto/statusline.sh` is optional and lives in the same place for the same
reason. If it exists, step 7's statusline sources it just before it closes the bar, so a
segment only this machine should have — spend on a work laptop, which account is logged in
— goes there rather than into a public repo. `statusline.sh.example` has the contract and
three worked segments; skip it entirely and the bar is exactly as it ships.

## 7. Point Claude Code at the statusline (skip if you do not use it)

Two keys in `~/.claude/settings.json`, and only two. Everything else in that file —
model, effort, permissions, plugin toggles, and `outputStyle` if another tool sets it — is left
alone.

```sh
# Claude Code does not write settings.json until you change a setting, so it may not
# exist yet. Seed it, then back it up — -n keeps the FIRST backup, so running this step
# twice cannot overwrite the pristine copy the undo in "Uninstalling" depends on.
[ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
cp -n ~/.claude/settings.json ~/.claude/settings.json.bak
# The transform reads your CURRENT settings, never the backup: .bak is a first-run
# snapshot, so re-running this a year later with .bak as input would roll back every
# setting you changed in between. .prev is just this run's before-picture for the diff.
cp    ~/.claude/settings.json ~/.claude/settings.json.prev

# Say so if you already have a statusline of your own. The step below keeps it.
jq -r '.statusLine.command // empty' ~/.claude/settings.json.prev \
  | grep -v statusline-agnoster.sh \
  | sed 's|^|kept your existing statusLine: |'

jq '
  def punto_sl: {"type": "command", "command": "~/.claude/statusline-agnoster.sh"};
  def rewire($e): .hooks[$e] = (
      ((.hooks[$e] // [])
       | map(.hooks |= map(select((.command // "") | test("(claude|agent)-notify\\.sh") | not)))
       | map(select((.hooks | length) > 0)))
      + [{"matcher": "", "hooks": [{"type": "command",
          "command": "$HOME/.tmux/agent-notify.sh claude"}]}]);
  .statusLine = (if (.statusLine | type) != "object"
                    or (.statusLine.command // "" | contains("statusline-agnoster.sh"))
                 then punto_sl else .statusLine end)
  | rewire("UserPromptSubmit") | rewire("PermissionRequest")
  | rewire("Notification") | rewire("Stop")
' ~/.claude/settings.json.prev > ~/.claude/settings.json.tmp \
  && mv ~/.claude/settings.json.tmp ~/.claude/settings.json \
  || rm -f ~/.claude/settings.json.tmp

diff <(jq -S . ~/.claude/settings.json.prev) <(jq -S . ~/.claude/settings.json)
rm -f ~/.claude/settings.json.prev
```

**It will not take a statusline away from you.** `.statusLine` is set only when the key is
absent or already points at `statusline-agnoster.sh`; anything else you had configured is
left exactly where it is, and the `jq -r` line above names it so you are not left guessing
why the bar did not change. Switching over is then yours to do deliberately:

```sh
jq '.statusLine = {"type": "command", "command": "~/.claude/statusline-agnoster.sh"}' \
   ~/.claude/settings.json > /tmp/s.json && mv /tmp/s.json ~/.claude/settings.json
```

`rewire` strips any existing notifier **hook** before adding the current one, so running
this twice does not give you two notifications per event. It matches `claude-notify.sh` as
well as the current `agent-notify.sh`, so an install made before the rename is repaired by
re-running this step rather than by editing JSON by hand.

It filters at the hook level, not the entry level, and that distinction is the whole
reason this is written out rather than done casually: one entry can hold several hooks. If
another tool's hook shares an entry with the notifier, dropping the entry takes that tool
out with it. `map(select((.hooks | length) > 0))` then removes an entry only once it is
genuinely empty.

The closing `diff` shows exactly what changed. Read it before moving on — it should name
`statusLine` and the four hook events and nothing else. On a re-run it prints nothing at
all, which is the correct result: the two keys are already what this step sets them to,
and everything you changed since is left where it is.

### The notification banner is opt-in

The two hooks give you a tmux status-line nudge when Claude finishes or wants permission
in a pane you are **not** looking at. That part is always on — it costs one line at the
bottom of a screen you are already reading.

A macOS notification banner on top of that is off unless you ask for it, because at one
per turn it is a lot of banners. Turn it on in `~/.config/punto/machine.zsh` (step 6):

```sh
export AGENT_NOTIFY_BANNER=1        # macOS banner as well as the tmux strip
export AGENT_NOTIFY_SOUND=Submarine # or "" for a silent banner
export AGENT_NOTIFY_APP=Ghostty     # only if the banner fires while you are watching
```

Outside tmux the banner is the only channel there is, so without it you get nothing.

`AGENT_NOTIFY_APP` names your terminal application, and matters only for the case where
the agent's pane is the one on screen but the screen is not what you are looking at. There
the status line has nothing to say — you would see it the moment you looked — so the
banner fires unless the terminal is the frontmost application. iTerm2 and Terminal are
recognised without this; set it if you get a banner for a turn you watched finish, to
whatever `lsappinfo info -only name "$(lsappinfo front)"` prints with your terminal in
front.

## 8. Codex (skip if you do not use it)

`brew install --cask codex` if you have not already. Two pieces: a title Codex publishes
for tmux to read, and a hook that tells you when it wants you.

**The title.** This one is added by hand, because Codex writes to `~/.codex/config.toml`
itself — it records per-project trust in there — so that file cannot be a symlink into a
public repo without your local project paths landing in its git history.

Add to `~/.codex/config.toml`:

```toml
[tui]
terminal_title = ["activity", "run-state", "thread-title"]
```

If the file already has a `[tui]` table, add the `terminal_title` line **inside it**. A
second `[tui]` is a duplicate-table error and Codex then loads no config at all — not just
no title. Check either way:

```sh
codex doctor --summary | grep -E 'config|title'   # expect ✓ on both
```

`run-state` is what earns the tab its state word: it renders `Ready`, `Working` or
`Action Required`, and `.tmux.conf`'s `@tab` shows those verbatim ahead of the name. It has to
be the **first `|`-separated field**, because that is where `@tab` reads it. `activity` may
sit ahead of it and often should — it is a prefix, not a field, rendering `⠦` while working
and a blinking `[ . ]` / `[ ! ]` while waiting, so it says the same thing in a bare terminal
window title where nothing is translating anything.

`thread-title` last, which assumes you name your threads — until one is named it renders
the raw thread UUID, accurate and useless in a 40-cell tab. Use `project` there instead if
you do not. `./check.py codex` tells you if the placement or the ordering stops the state
word reaching the tab; it does not have
an opinion about the last field.

**The hook.** This file Codex only reads, so step 5 already symlinked it:

```sh
ls -l ~/.codex/hooks.json          # -> ~/punto/dotfiles/codex/.codex/hooks.json
```

It wires `agent-notify.sh` to `PermissionRequest` and `Stop`, the same two moments step 7
wires for Claude. Then start `codex` once and run `/hooks` to review and trust it — Codex
will not run a hook you have not approved, and says nothing when it skips one.

## 9. opencode (skip if you do not use it)

`brew install opencode` if you have not already. One file, and step 5 already symlinked it:

```sh
ls -l ~/.config/opencode/plugins/tmux-agent.ts
# -> ~/punto/dotfiles/opencode/.config/opencode/plugins/tmux-agent.ts
```

Nothing else to register and nothing to approve. opencode has no hooks file: every file in
`~/.config/opencode/plugins/` is loaded at startup and subscribes to the event bus, which is
the one place opencode is easier than Codex, where a hook you have not trusted is skipped
silently.

The plugin builds the same JSON payload Claude Code and Codex deliver on stdin and pipes it
into `~/.tmux/agent-notify.sh`, so the state word, the notice, the collapse past one pending
notice and `AGENT_NOTIFY_BANNER` all work the same way. Five kinds of moment reach it: the
message you send, a permission request, a question with options, your answer to either, and
the session going idle. A permission notice names the permission opencode asked for —
` ◆  opencode w2.1  punto — bash ` — rather than the reason, which opencode does not put on
the event the way Claude and Codex do; a question notice names the question's own short
header, which opencode caps at 30 characters for exactly this kind of use.

Start `opencode` inside tmux once. The tab should read `Working | <project>` while it works
and `Ready | <project>` when it stops.

**If the tab reads `▶ opencode` instead** — the command you typed, with a `▶` in front of it
rather than a state word — the pane's command is not what `@agent_is` matches. Homebrew's
`opencode` is a wrapper that execs a Bun-compiled `opencode.exe`, so the pane runs the second
name and not the first; both are matched, but another install route may use a third. Check
what it actually is, and add that to `@agent_is` in `dotfiles/tmux/.tmux.conf`:

```sh
tmux display -p '#{pane_current_command}'      # expect: opencode.exe, or opencode
```

**If the tab reads the project name and never a state word**, the plugin is not running. It
disables itself outside tmux by design, so start opencode in a pane rather than a bare
terminal window; if it already is one, `./check.py opencode`.

The name in the tab is the session name, which opencode publishes in its pane title as
`OC | <session>` and which `/rename` inside opencode sets. Until a session has one the title
is a bare `OpenCode`, and the tab shows the pane's working directory instead — so a fresh
pane reads `Ready | punto` and the same pane reads `Ready | notifications` once you have
named the session. If you would rather it were always the directory, the one line to change
is `@agent_name` in `dotfiles/tmux/.tmux.conf`.

## 10. The commit hook

Skip only if you will never commit in this clone.

```sh
cd ~/punto
pre-commit install          # brew installed pre-commit itself in step 2
pre-commit run --all-files  # first run downloads each hook; about a minute
```

**Per clone, not per machine.** `pre-commit install` writes `.git/hooks/pre-commit`, and
git does not clone hooks — a second clone of this repo starts with none, silently.

gitleaks scans the staged diff against ~150 credential patterns and fails the commit. It
is the only control here that catches a secret pasted into a file that is already tracked;
`.gitignore` cannot, because the file is already in. Commit time is the cheap moment —
git history is permanent, and a credential that lands in a commit is burned whatever a
later commit removes.

## 11. First run

In order. Each step needs the one before it.

```sh
exec zsh                 # 1. new shell, new config
```
```
tmux                     # 2. then press C-a I — TPM fetches its four plugins
```
```sh
nvim                     # 3. lazy.nvim fetches its plugins, then mason fetches the LSPs
```

`C-a` is the tmux prefix: hold Ctrl, tap `a`, release, then tap `I` (capital).

## 12. Check

```sh
./check.py
```

Read-only — it opens files and runs read-only commands, and has no code path that writes
anything.
Expect `✔ all good`. Anything else names the step to go back to.

Run one section on its own with `./check.py links`, or `tools`, `clones`, `machine`,
`claude`, `repo`.

---

## Updating

```sh
cd ~/punto && git pull
```

That is the whole update. The files in `$HOME` are symlinks into this repo, so a pull
changes them in place.

Two exceptions, both rare:

- **A new file appeared in a package.** Nothing links it yet — rerun steps 4 and 5.
  `./check.py links` says `missing` when this has happened.
- **`machine.zsh.example` gained a setting you want.** Copy the line across by hand;
  your `machine.zsh` is deliberately never overwritten.
- **`claude-notify.sh` became `agent-notify.sh`.** One notifier now serves Claude and
  Codex. `./check.py claude` fails while `~/.claude/settings.json` still names the old
  path; re-run step 7 to fix it, and `rm ~/.tmux/claude-notify.sh` — that symlink is
  dangling, and the uninstall loop no longer knows the name to remove it.
- **The macOS banner is now opt-in, and you will notice.** The old notifier raised one
  unconditionally; this one raises none until `AGENT_NOTIFY_BANNER` is set. Outside tmux
  that leaves you with nothing at all. `CLAUDE_NOTIFY_SOUND` was renamed to
  `AGENT_NOTIFY_SOUND` and the old name does nothing — put both in
  `~/.config/punto/machine.zsh`, which `machine.zsh.example` now shows.

## Uninstalling

```sh
cd ~/punto
for pkg in dotfiles/*/; do
  (cd "$pkg" && find . -type f ! -name '.DS_Store' | sed 's|^\./||') | while read -r rel; do
    [ -L "$HOME/$rel" ] && rm "$HOME/$rel"
  done
done
```

Only removes symlinks — `[ -L ]` means a real file you created later is left alone. That
loop takes `~/.codex/hooks.json` with it, but not the `[tui]` block you added by hand to
`~/.codex/config.toml`; delete that yourself or Codex keeps publishing a title nothing
reads. Then copy back whatever step 5 saved in `~/punto-backup/<timestamp>/`, and put
`~/.claude/settings.json.bak` back to undo step 7.
