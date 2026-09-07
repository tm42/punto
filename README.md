# punto

zsh, tmux and Neovim, set up to behave as one environment rather than three programs that
happen to share a terminal. Machine-specific paths and every credential stay out of the repo.

macOS and Linux. MIT.

A personal setup, published so I can reproduce it on a new machine — not a framework and not
a distribution. Ideas and corrections are welcome. It changes when my setup changes, with no
notice and no migration path, so fork it rather than track it.

Installing is done by hand, following [INSTALL.md](INSTALL.md) — about fifteen minutes, once
per machine. There is no installer on purpose: after the first install `git pull` *is* the
update, because every file in `$HOME` is a symlink into this repo and is already live.

```bash
git clone https://github.com/tm42/punto ~/punto
cd ~/punto
$EDITOR INSTALL.md      # read it, then follow it
./check.py              # read-only: did it work?
```

---

## check.py

The only program here, and it is **read-only** — it opens files and runs a handful of
read-only commands, and has no
code path that writes, creates or deletes anything. That is why it exists and the installing
does not: checking that every symlink actually resolves into this repo is tedious by hand and
cannot hurt you if it is wrong.

```bash
./check.py               # everything
./check.py links tools   # one or more sections
```

Sections: `links`, `tools`, `clones`, `machine`, `claude`, `repo`. It checks that every
managed path is a symlink into this repo (naming anything that is a real file, a broken link,
or a link somewhere else), that the Homebrew formulae and the Nerd Font cask are installed,
that each third-party clone is a real clone rather than an empty directory left by a failed
one, that `machine.zsh` names project roots **that exist**, that Claude Code points at the
statusline and the notifier, and that no credential file is tracked.

---

## How the linking works

The real file lives in the repo; `$HOME` gets a signpost pointing at it.

```
~/.zshrc  ──▶  ~/punto/dotfiles/zsh/.zshrc
```

So editing `~/.zshrc` *is* editing the repo file — `git diff` shows it immediately, and there
is no "remember to copy it back" step to forget, and `git pull` updates your live config with
no install step at all. GNU Stow is the usual tool for this; INSTALL.md uses an `ln -s`
loop instead, so there is nothing to install before you can install. That loop moves any
real file it would replace into `~/punto-backup/<timestamp>/` and refuses to write through
a symlinked parent directory into someone else's checkout.

Each package is a directory under `dotfiles/` whose contents mirror `$HOME`:

```
dotfiles/
  zsh/     .zshrc
  tmux/    .tmux.conf + .tmux/{pane-status.zsh,git-status.sh,sessionizer.sh,
                               cheat.sh,agent-notify.sh}
  nvim/    .config/nvim/{init.lua,lazy-lock.json,lua/**}
  claude/  .claude/statusline-agnoster.sh
  codex/   .codex/hooks.json
  opencode/ .config/opencode/plugins/tmux-agent.ts
  docs/    .nvimcheatsheet.md, .tmux-quickstart.md
```

**The scope rule:** this repo is the terminal environment — zsh, tmux, nvim, and the tools
those three call. Nothing else. Other tools that install themselves are not in it and are
not touched by it, even where they write to the same files.

Coding agents are in scope only where they render into the terminal. For Claude Code that
is `statusline-agnoster.sh`, whose palette is matched to the agnoster prompt; INSTALL.md
step 7 writes `statusLine` and an `agent-notify.sh` entry on four hooks —
`UserPromptSubmit`, `PermissionRequest`, `Notification`, `Stop` — and leaves every other key
alone, including hooks belonging to other tools that share an entry with it. `statusLine` it
writes only when the key is absent or already this repo's: a statusline you configured
yourself survives, and the step names it rather than leaving you to wonder.

Codex is the same two seams and one file less: it draws its own status line, so all this
repo ships is `hooks.json`. Its `[tui].terminal_title` is added by hand rather than
symlinked, because Codex writes per-project trust into `~/.codex/config.toml` and a
symlink would put your local project paths into a public git history.

opencode loads every file in `~/.config/opencode/plugins/` at startup, so `tmux-agent.ts` is
the whole wiring and the link in step 5 is the whole install — nothing to register, nothing
to approve. The plugin builds the same JSON payload the other two deliver on stdin and pipes
it into `agent-notify.sh`, which is the point: one notifier keeps its foreground test, its
four escapes, its notice and its banner, and a second copy of them in TypeScript would have
drifted from the first by the next change.

### Not vendored

oh-my-zsh and its two custom plugins, TPM and its four tmux plugins, lazy.nvim. Other
people's repos on their own cadence; INSTALL.md step 3 clones them. lazy.nvim is not even cloned —
`init.lua` fetches it on first launch. `lazy-lock.json` **is** tracked, so both machines
resolve the same plugin commits.

---

## What is actually integrated

Four seams, none of them obvious from the individual files.

### One movement grid across nvim splits and tmux panes

`M-h/j/k/l` moves left/down/up/right — through an nvim split boundary and out into the
neighbouring tmux pane without changing key. tmux decides which it is: `is_vim` in
`.tmux.conf` reads the pane's process table and forwards the key when nvim is running there,
consuming it otherwise.

The regex is written to work on BSD grep as well as GNU. Upstream ships `\S` and `[^ ]*`;
older BSD greps read `\S` as a literal `S`, and `[^ ]*/` refuses to backtrack to empty.
`(.*/)?` is the form that works on both, and on every version.

(The `\S` half no longer bites: BSD grep 2.6.0-FreeBSD, which current macOS ships, handles
it correctly. `(.*/)?` costs nothing, so it stays.)

`M-H/J/K/L` resizes by one cell, repeatable, and lives in `.tmux.conf` alone — nvim has no
say in resizing. The *movement* keys above are the ones both halves must agree on: they are
mapped in `.tmux.conf` and in `nvim/lua/plugins/tmux-navigator.lua`, and changing one
silently breaks the other.

### The window tab tells you what the pane is doing

`@tab` is four branches, first match wins, every one capped at exactly 40 display cells:

| Pane is | Tab shows | Example |
|---|---|---|
| nvim | `✎:` + repo/file | `✎:punto/README.md` |
| an agent, working | `Working \| ` + name | `Working \| punto` |
| an agent, blocked on you | `Action Required \| ` + name | `Action Required \| punto` |
| an agent, finished and unread | `Ready \| ` + name | `Ready \| testing-session` |
| an agent, idle | name | `testing-session` |
| running a command | `▶` + command | `▶ pytest -x` |
| finished a command | `✔` or `✘<code>` + command | `✘1 cargo build` |
| idle | cwd basename | `~` |

All three agents render in Codex's own words, because Codex picked good ones and the rule
is then a sentence: **the tab shows what Codex would say.** For Codex it is close to a
passthrough of its pane title — strip the `activity` prefix, keep the rest. For Claude and
for opencode the same string is synthesised from hooks, because both publish a pane title
that never changes. Claude's is a constant `✳ <session>`: sampled 14 times over 5.6s
mid-turn, it was byte-identical every time, and the spinner frames an earlier version of
this config matched for do not exist. opencode's is `OpenCode` until you send it anything and
`OC | <session>` after that, so it names the session and never the project: the prefix is
stripped and the session shown, with the pane's working directory standing in until the
session has a name. `/rename` inside opencode is what sets it.

| State | Codex | Claude | opencode |
|---|---|---|---|
| `Working` | its title | `UserPromptSubmit` hook | `UserPromptSubmit`, from `message.updated` |
| `Action Required` | its title | `PermissionRequest` hook | `PermissionRequest`, from `permission.asked` or `question.asked` |
| `Ready` | `Stop` hook — **not** its title | `Stop` and `Notification` hooks | `Stop`, from `session.idle` |
| idle | visiting the pane clears `Ready` | visiting the pane clears `Ready` | visiting the pane clears `Ready` |
| interrupted | its title | screen unchanged for 30s clears `Working` | screen unchanged for 30s clears `Working` |

`Ready` is the row worth reading twice. Codex's title reports `Ready` for a turn that just
ended *and* for a pane nobody has touched since yesterday, so the title alone cannot tell
you a question is waiting — which is exactly the case where Codex finishes by asking you
something. It comes from `Stop` for both agents instead, and a turn that ends while you are
looking at the pane clears the state rather than setting it, because "unread" is false when
you are reading it.

A live `Working` title is checked before everything, so approving a Codex request corrects
the tab at once. **Claude has no such title**, so its `Action Required` stands until the turn
ends — a bounded lie, and the alternative is a hook on every tool call. `Action Required` is
also the one state visiting does not clear: an approval you have looked at and not answered
is still an approval.

Claude's `Notification` maps to `Ready`, not to `Action Required`, because it fires both for
a permission prompt and after sitting idle 60 seconds — and the second is the opposite of
blocked on you. `PermissionRequest` is the event that means only the one thing. `Notification`
then declines to overwrite an existing `Action Required`, since Claude fires it 60 seconds
into a prompt that is still pending.

From Claude it also raises no notice, which is the one place a state and a notice part
company. Every
other event reports a change, so every other event is news exactly once; this one reports
that nothing has changed, and repeats for as long as nothing does. Sampled on a real pane: a
turn ended at 19:31:19, its notice aged out after the usual 30 seconds, and at 19:32:19 —
60 seconds to the second — `Notification` put the same pane back in the bar as
` ◆  claude w1.1  flw — Claude is waiting for your input `, a fresh notice for a turn that
had already finished and been read. Claude only: both halves of that argument are about
Claude, and an agent that sent this event name for something that mattered would go silent
with no other way to reach the bar, so every other agent keeps the notice it had.

The pane border carries the same label, from the same two options — a tab can only ever
speak for the active pane, so in a split window the other agent would otherwise show the
border's `@ps_cmd`, which for an agent pane is frozen at `▶ codex` from the moment zsh's
`preexec` saw the launch.

Anything else falls through and the remaining title is shown verbatim. That is the design,
not a gap: a Codex run-state nobody has seen yet is already a word, so an untranslated
state still reads correctly — `Compacting | punto` costs nothing.

The exit glyph survives the command, which is the point — a build that failed while you were
in another window still says so. Visiting the pane acknowledges it and the tab drops back to
the directory name; `▶` is never cleared that way, because a running command is not news you
have already read.

`~/.tmux/pane-status.zsh` hooks zsh's `preexec`/`precmd` and publishes `@ps_state`, `@ps_cmd`,
`@ps_code` and `@ps_dur` as tmux pane options; `.tmux.conf` renders them. The nvim branch
reads the terminal title, which `nvim/lua/options.lua` sets — and truncates there rather than
in tmux, because tmux's `#{=/-N/…:}` can only blind-cut a tail and that eats the repo name
whole. Both caps are 37 on purpose: at 37 tmux's backstop never fires, so you never get a
second `…`.

An agent's notice is drawn by `status-tick.sh` at the right of the status bar, ahead of git
and the clock, not by `display-message`, whose timeout tmux cancels on your next keystroke:
a notice about window 4 used to die because you typed in window 1. This one goes when you
reach the pane it names, or after 30s. Notices are pane-scoped, so several can be pending at
once; past one they collapse to a count and the list of names.

The same script is what makes `Working` honest. State is latched by hooks, and Claude fires
none when a turn is interrupted with Esc or killed, so the latch outlives the turn. A
working pane redraws, though: measured against a real turn, no two consecutive 3s samples of
its screen matched while it streamed, and it held one value from the moment Esc landed. So a `Working` pane whose
screen has not changed for 30s loses the state — held through 31s of streaming and cleared
28s after the interrupt, in the run that decided the threshold.

### Prompt and Claude statusline are one bar

The agnoster segments — host, venv, path, git — and Claude Code's statusline use the same hex
values, so the prompt and the bar above it read as one unit. The zsh half is `.zshrc` §3; the
other half is `statusline-agnoster.sh`.

Two rules the two halves share. `user@host` is drawn only when it is not the obvious one —
the prompt asks that as root, another user, or SSH; the statusline asks it as root or SSH,
because `$DEFAULT_USER` is a shell variable no hook script is handed. The venv segment is
labelled `V:` in both, since naming it after the project rather than after `.venv` makes a
bare name read as one more path component.

The theme itself is stock. Colours are twelve `AGNOSTER_*` variables agnoster reads as
defaults, exported in §3 before it loads. What no variable reaches is redefined in §5, after
oh-my-zsh sources the theme: a truncated path (`prompt_dir`), typing on the second line
(`PROMPT`), `user@host` only over SSH or as another user (`prompt_context`, which stock draws
always and hides in a remote tmux, because it tests `SSH_CLIENT` and tmux carries
`SSH_CONNECTION`), and a venv named after the project rather than after the `.venv` directory
(`prompt_virtualenv`, which stock gates on a variable only the unloaded `virtualenv` plugin
exports, so it never drew and `activate` prepended its own uncoloured `(.venv) ` instead).
**Nothing here edits the theme file**, because it lives in the
vendored `~/.oh-my-zsh` clone: oh-my-zsh updates itself with `git pull --rebase` under
`rebase.autoStash`, so an edit there is stashed and replayed — it survives while upstream
leaves that file alone, then lands as a rebase conflict the first time upstream touches it.
`./check.py clones` warns when one of those clones is dirty for that reason.

That script's second line is a load gauge: model, effort, and context percent. The 5-hour and
7-day rate-limit windows are **not** shipped — they are your plan and your usage rather than a
terminal setting, so they live in `~/.config/punto/statusline.sh` and
`statusline.sh.example` says where to get them. Two details worth knowing:

- **Context bands escalate earlier on a 1M window** (10/20/40% instead of 20/40/60%), because
  effective attention degrades long before the tokens fill.
- **The green `1m` badge** tracks the effective window size, not the model string, so it does
  not flicker when Claude Code drops the `[1m]` suffix on its own.
- **A `1m✗` badge** means the model id still says `[1m]` while the served window is 200k — the
  long-context credit clamp. That one *is* keyed on the id, so it says what Claude Code claims
  rather than what it delivers.

Hex colours need a truecolor terminal, and under tmux Claude Code additionally needs
`CLAUDE_CODE_TMUX_TRUECOLOR=1` (`.zshrc` §3), or it clamps 24-bit to the 256 cube and the
palette collapses into itself.

The bar takes one local addition, the same way `.zshrc` takes `~/.zshrc.local`: if
`~/.config/punto/statusline.sh` exists it is **sourced** just before the closing arrow, so
it inherits `$input`, the palette and `$PREV_FG`. Print a segment, set `PREV_FG` to your own
background, and the bar closes on your colour. That is where a work laptop's spend segment
belongs — per machine, never in a public repo. It runs on every render, so anything reaching
the network there stalls the bar; cache to a file and read the file.

### The agents tell you when they need you, in one vocabulary

`~/.tmux/agent-notify.sh` serves all three. Claude Code and Codex deliver the same hook
payload — a JSON object on stdin with `.hook_event_name` and `.cwd` — and the opencode
plugin builds that payload itself from the event bus, so one script handles four events from
Claude, two from Codex and three from opencode, and takes the label from its first
argument. It
raises a tmux notice only when that agent's pane is in the background, and always exits 0:
a hook that errors nags the agent, not you. It also sets the `@agent_state` the window tab
and pane border read.

Each notice is a pane-scoped option, so several can be pending at once. Past one they
collapse to a count and a list of names — ` ◆  3 agents  ·  flw, punto, system-setup ` —
because three verbs will not fit on a line already carrying git, the clock and the date,
and the count is the news anyway. A `◆` anywhere in the set wins over `✳`: a pane blocked
on you outranks two that merely finished.

The macOS banner is off until you export `AGENT_NOTIFY_BANNER` — at one per turn it is a
lot of banners, and the tmux strip already says it where you are looking. Which also means
that outside tmux you get nothing until you export it. When the pane *is* on screen but
the terminal is not the frontmost app, the banner is the only channel that can reach you,
so that is the one case where it fires for a foreground pane. Which terminal you are in
is read from the tmux server's environment and not from `$TERM_PROGRAM`, because tmux
overwrites that with `tmux` inside every pane.

---

## Keys worth knowing

Prefix is `C-a`. Alt bindings are prefix-less.

### tmux

| Key | Does |
|---|---|
| `M-o` | fzf project picker — attach-or-create one session per directory, open sessions first |
| `M-s` | floating scratch shell; same session every time, so it keeps its history. Same key closes it |
| `M-\` | copy mode |
| `M-[` / `M-]` | previous / next window |
| `M-0`…`M-9` | jump to window N |
| `C-a F` | fuzzy-search every tmux command with a live man-page preview |
| `C-a g` | thumbs — hint letters on every path/url/hash on screen; press one to copy |
| `C-a Tab` | extrakto — fuzzy-search every token on screen and in scrollback |
| `C-a \|` / `C-a -` | split vertical / horizontal, inheriting the current path |
| `C-a z` | zoom pane (the bar says `ZOOM`, which is why you stop losing panes) |
| `C-a r` | reload config |
| `C-a ?` | this config's quickstart, in a popup |

`M-o` was `M-f` until a terminal's opt+right turned out to send `M-f`, which zsh uses for
forward-word — tmux ate it before the shell saw it.

`C-a F` is worth a minute: every tmux command with a one-sentence description, searchable by
concept, and the preview decodes tmux's opaque single-letter flags. Typing `link` finds
`link-window`, `swap-window` and `move-window` — the whole family, because each one's sentence
names the others.

### Neovim

Leader is Space. Press it and wait — which-key lists everything. Full sheet at
`~/.nvimcheatsheet.md`, which `<leader>?` opens in a split. tmux has the matching pair:
`~/.tmux-quickstart.md` on `C-a ?`.

### zsh

`fzf-tab` replaces the completion menu with a fuzzy finder. Autosuggestions come from history;
`→` accepts. `zoxide` learns your directories: `z proj` jumps.

`.zshrc` §7's load order is mandatory and the file says so in place. Each plugin wraps the ZLE
widgets installed before it: fzf-tab needs `compinit` to have already run, and syntax
highlighting must be dead last or it never sees — and so never colours — what the others
installed.

---

## Secrets and per-machine values

Nothing here is a credential, and the split that keeps it that way is structural rather than
disciplinary. Three files are read at shell startup and none is committed:

| File | Holds | Seeded by |
|---|---|---|
| `~/.config/secrets/secrets.zsh` | API keys and tokens, mode 600 | you |
| `~/.config/punto/machine.zsh` | per-machine paths | you, from `machine.zsh.example` (INSTALL.md step 6) |
| `~/.config/punto/statusline.sh` | per-machine statusline segments | you, from `statusline.sh.example`; optional |
| `~/.zshrc.local` | anything else this one machine needs | you, if ever |

A token has no *reason* to live in a tracked file — that is the actual protection. `.gitignore`
is a backstop and a weak one: it cannot help with a secret pasted into a file that is already
tracked.

**The control that works is the pre-commit hook.** gitleaks scans the staged diff against ~150
credential patterns and fails the commit:

```bash
pre-commit install     # per clone — INSTALL.md step 10; git does not clone hooks
```

Commit time is the only cheap moment. Git history is permanent — a credential that lands in a
commit is burned regardless of what a later commit removes.

Two non-obvious habits:

- **`uv … --help` prints live secrets.** uv renders environment defaults as `[env: VAR=<value>]`,
  so any `UV_*` secret in your environment leaks to scrollback, CI logs, or a screen share.
  Put `keyring-provider = "subprocess"` in your own `~/.config/uv/uv.toml` and use the system
  keychain instead. Not shipped here — uv is not one of the tools this repo covers.
- **`~/.claude/shell-snapshots/` freezes your shell environment at session start**, tokens
  included. Gitignored here; leave it that way.

### The four things that differ per machine

1. **Homebrew prefix** — `.zshrc` §1 probes `/opt/homebrew`, `/usr/local` and
   `/home/linuxbrew/.linuxbrew`. `brew --prefix` cannot answer, because brew is not on `PATH`
   until that block puts it there.
2. **`$HOME`** — `.tmux.conf` uses `#{HOME}`; tmux resolves an unknown format name from the
   environment.
3. **Project roots** — `TMUX_SESSIONIZER_ROOTS` and `TMUX_SESSIONIZER_EXTRA`, colon-separated,
   in `machine.zsh`. Roots are scanned at depth 1 *and* 2, so both `$root/apps` and
   `$root/apps/thing` are offered.
4. **Anything else** — `machine.zsh`, or `~/.zshrc.local` which `.zshrc` §11 sources last.

Git config is deliberately absent: identity, signing and remotes differ enough between a
personal and a work machine that syncing them is a liability. Nothing here needs it — the
status-bar branch segment, `git-status.sh` and gitsigns all call git plumbing directly and
work with no configuration at all.
