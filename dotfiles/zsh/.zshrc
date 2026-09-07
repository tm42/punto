# ─────────────────────────────────────────────────────────────
# .zshrc — interactive shell
#
# The section order below is load-bearing, not cosmetic: §4 must precede §5,
# and §7 must come after both. Each section says why.
#
# Two files are sourced and neither is in this repo:
#   ~/.config/secrets/secrets.zsh        API keys and tokens (chmod 600)
#   ~/.config/punto/machine.zsh          per-machine paths — see machine.zsh.example
# Nothing machine-specific or secret belongs in this file.
# ─────────────────────────────────────────────────────────────

# ── 1. PATH ──────────────────────────────────────────────────
# `typeset -U` keeps the array unique with the first occurrence winning, so the
# prepends in ~/.config/punto/machine.zsh can't introduce duplicates.
# Appending to $path instead of assigning a literal string preserves whatever
# /etc/paths.d contributed — a hardcoded assignment silently drops entries like
# ~/.orbstack/bin.
#
# Only Homebrew's own directories are added here. A tool this repo does not
# install — uv, bun, cargo, anything else — goes on PATH in machine.zsh, guarded
# by [ -d ], so a machine that lacks it carries no dead entry.
typeset -U path PATH

# Homebrew's prefix varies by platform: /opt/homebrew on Apple Silicon,
# /usr/local on Intel, /home/linuxbrew/.linuxbrew on Linux. `brew --prefix`
# cannot answer here — brew is not on PATH until this block puts it there.
BREW_PREFIX=""
for _p in /opt/homebrew /usr/local /home/linuxbrew/.linuxbrew; do
  [[ -x $_p/bin/brew ]] && { BREW_PREFIX=$_p; break }
done
unset _p

[[ -n $BREW_PREFIX ]] && path=(
  $BREW_PREFIX/bin                # ahead of /usr/bin: OpenSSL 3.x over Apple's LibreSSL
  $BREW_PREFIX/opt/openjdk/bin
  $path
)

# GUI-app CLIs, macOS only. Guarded on existence so a machine without either
# does not carry a dead PATH entry.
if [[ $OSTYPE == darwin* ]]; then
  for _p in "/Applications/Visual Studio Code.app/Contents/Resources/app/bin" \
            /Applications/iTerm.app/Contents/Resources/utilities; do
    [[ -d $_p ]] && path=("$_p" $path)
  done
  unset _p
fi

# ── 2. Secrets and machine values ────────────────────────────
# Early, so everything below can see the tokens and paths.
[[ -f ~/.config/secrets/secrets.zsh ]]  && source ~/.config/secrets/secrets.zsh
[[ -f ~/.config/punto/machine.zsh ]]    && source ~/.config/punto/machine.zsh

# ── 3. Environment ───────────────────────────────────────────
export EDITOR="nvim"
export ZSH="$HOME/.oh-my-zsh"
export CLAUDE_CODE_TMUX_TRUECOLOR=1

# agnoster colours, matched to the Claude statusline's "teal native" palette.
# The shared first-line segments — host, venv, path, git — use the same values in
# both, so the prompt and the statusline read as one bar. See
# ~/.claude/statusline-agnoster.sh for the other half.
#
# Hex needs zsh 5.7+ (prompt_segment feeds these to both %K{} and %F{}) and a
# truecolor terminal; under tmux that also needs CLAUDE_CODE_TMUX_TRUECOLOR above
# for Claude Code's own rendering, though the prompt itself is unaffected by it.

# user@host — identity family, lightest. Drawn only over SSH or as another
# user; see the prompt_context override in §5.
export AGNOSTER_CONTEXT_BG='#6b9daf'
export AGNOSTER_CONTEXT_FG='#0d0d0d'

# virtualenv — identity family, middle
export AGNOSTER_VENV_BG='#5e7c87'
export AGNOSTER_VENV_FG='#0d0d0d'

# working directory — identity family, darkest; was ANSI `blue`, the one segment
# whose colour the terminal profile could change out from under the theme
export AGNOSTER_DIR_BG='#2e6072'
export AGNOSTER_DIR_FG='#f4f4f4'

# git — xterm 151 and 230 kept verbatim, the two colours worth not touching
export AGNOSTER_GIT_CLEAN_BG='#afd7af'   # sage
export AGNOSTER_GIT_CLEAN_FG='#0d0d0d'
export AGNOSTER_GIT_DIRTY_BG='#ffffd7'   # buttermilk
export AGNOSTER_GIT_DIRTY_FG='#0d0d0d'

# exit status / root / background jobs — no counterpart in the statusline, but
# left stock it renders ANSI black-and-red against all of the above
export AGNOSTER_STATUS_BG='#1d424f'
export AGNOSTER_STATUS_FG='#f4f4f4'
export AGNOSTER_STATUS_RETVAL_FG='#e27b70'   # ctx band 4 coral
export AGNOSTER_STATUS_ROOT_FG='#f6ce06'     # effort low yellow
export AGNOSTER_STATUS_JOB_FG='#89c9e9'      # week band 3

ZSH_THEME="agnoster"

# ── 4. Completion fpath — BEFORE oh-my-zsh ───────────────────
# oh-my-zsh runs compinit itself in §5. Brew's site-functions have to be on
# fpath before that happens or those completions are invisible; this file used
# to run a second compinit further down purely to catch them.
[[ -n $BREW_PREFIX ]] && FPATH="${BREW_PREFIX}/share/zsh/site-functions:${FPATH}"

# ── 5. oh-my-zsh and the prompt ──────────────────────────────
# zsh-autosuggestions and zsh-syntax-highlighting are deliberately absent here.
# They wrap ZLE widgets and must load after fzf-tab in a fixed order — see §7.
# Listing them here loaded them a second (and third) time, out of order.
#
# per-directory-history: lib/history.zsh below sets share_history, and the
# plugin tests that option itself and appends to both files immediately when
# it is on, so the two agree about when a line reaches disk.
plugins=(git you-should-use zsh-bat per-directory-history)
[[ -f $ZSH/oh-my-zsh.sh ]] && source $ZSH/oh-my-zsh.sh

# Two changes to the agnoster theme, which lives in the vendored ~/.oh-my-zsh
# clone. They are made here, after the theme is sourced, because oh-my-zsh
# updates itself with `git pull --rebase` under rebase.autoStash: an edit inside
# that clone is stashed and replayed, so it survives until upstream touches the
# same file and then comes back as a rebase conflict.

# Path: stock agnoster prints all of %~, which in a deep tree pushes the git
# segment past the right edge. %(4~|.../%3~|%~) is zsh's own conditional — four
# or more components, print the last three behind an ellipsis, else print it
# whole — so no subshell forks per prompt. Drops stock's AGNOSTER_GIT_INLINE
# branch, which nothing here sets.
prompt_dir() {
  prompt_segment "$AGNOSTER_DIR_BG" "$AGNOSTER_DIR_FG" '%(4~|.../%3~|%~)'
}

# Identity: only when it is not the obvious one. Stock hides user@host when
# $USERNAME matches $DEFAULT_USER, a variable it never sets, so the segment
# always drew. It also tests $SSH_CLIENT alone, which tmux does not carry into a
# pane — update-environment's default lists SSH_CONNECTION, not SSH_CLIENT — so
# stock would hide it in a remote tmux, the one place it is worth the width.
DEFAULT_USER=${DEFAULT_USER:-$USER}
prompt_context() {
  if [[ $UID -eq 0 || $USERNAME != $DEFAULT_USER || -n $SSH_CONNECTION || -n $SSH_TTY ]]; then
    prompt_segment "$AGNOSTER_CONTEXT_BG" "$AGNOSTER_CONTEXT_FG" \
      "%(!.%{%F{$AGNOSTER_STATUS_ROOT_FG}%}.)%n@%m"
  fi
}

# Virtualenv: stock gates its segment on VIRTUAL_ENV_DISABLE_PROMPT, exported by
# oh-my-zsh's virtualenv plugin, which §5 does not load — so the segment never
# drew and `activate` prepended its own uncoloured "(.venv) " to the bar instead.
# Exporting the variable drops that prefix. The override then names the project,
# because ${VIRTUAL_ENV:t} is ".venv" for every project-local venv and tells you
# nothing; it is the rule statusline-agnoster.sh uses for the same segment.
# Shows an activated venv only: the prompt describes this shell, and
# `uv pip install --python .venv/bin/python` never activates one.
# Drops stock's conda branch — nothing here uses conda.
# The "V:" is there because naming the venv after the project makes it read as
# another path component next to the segment that actually is one.
export VIRTUAL_ENV_DISABLE_PROMPT=1
prompt_virtualenv() {
  [[ -n $VIRTUAL_ENV ]] || return
  local name=${VIRTUAL_ENV:t}
  [[ $name == .venv ]] && name=${VIRTUAL_ENV:h:t}
  prompt_segment "$AGNOSTER_VENV_BG" "$AGNOSTER_VENV_FG" "V:${name:gs/%/%%}"
}

# Type on line 2. Stock leaves the cursor on the same line as the segment bar,
# which in a git repo is most of the terminal width.
PROMPT='%{%f%b%k%}$(build_prompt)
$ '

# ── 6. Tool integrations ─────────────────────────────────────
# Every line here is guarded, so a machine missing the tool loses the feature
# and nothing else.
(( $+commands[zoxide] )) && eval "$(zoxide init zsh)"
[ -e "$HOME/.iterm2_shell_integration.zsh" ] && source "$HOME/.iterm2_shell_integration.zsh"

# ── 7. ZLE widget plugins — this order is mandatory ──────────
# Each of these wraps the widgets installed before it. fzf-tab needs compinit
# (done in §5) to already have run; syntax highlighting must be dead last or it
# never sees — and so never colours — what the others installed.
if [[ -n $BREW_PREFIX ]]; then
  for _f in fzf-tab/fzf-tab.zsh \
            zsh-autosuggestions/zsh-autosuggestions.zsh \
            zsh-syntax-highlighting/zsh-syntax-highlighting.zsh; do
    [[ -f $BREW_PREFIX/share/$_f ]] && source $BREW_PREFIX/share/$_f
  done
  unset _f
fi
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=245'

# ── 8. tmux pane status ──────────────────────────────────────
# preexec/precmd hooks publishing @ps_state/@ps_cmd/@ps_code/@ps_dur, rendered
# by window-status-format and pane-border-format in ~/.tmux.conf.
[[ -f ~/.tmux/pane-status.zsh ]] && source ~/.tmux/pane-status.zsh

# ── 9. Aliases ───────────────────────────────────────────────
alias vim="nvim"
alias bp='bat --plain'
alias bct='bat --paging=never'

# ── 10. claudea ──────────────────────────────────────────────
# claudea = claude + whatever is in ~/.claude/append.md, for per-project instructions or
# experiments. Prose and formatting rules do NOT belong there — the output-style slot is
# the only one that gets a per-turn reminder, and rules without reinforcement decay over a
# long session. No-ops to plain claude when the file is absent.
claudea() {
  local f=~/.claude/append.md
  if [[ -r $f ]]; then
    command claude --append-system-prompt "$(<$f)" "$@"
  else
    command claude "$@"
  fi
}

# ── 11. Local overrides ──────────────────────────────────────
# Last word, for anything this machine needs that the repo should not carry.
#
# An `if`, not `[[ -f … ]] && source …`. This is the last line in the file, so
# its status is what the first prompt sees, and the && form exits 1 when the
# file is absent — which is every machine that has just run INSTALL.md. agnoster
# then paints its red retval segment on the first prompt of every new shell,
# reporting an error that refers to nothing. A false `if` exits 0.
#
# Deliberately no trailing `true`: if ~/.zshrc.local itself ends in something
# that failed, the ✘ is earned and worth seeing.
if [[ -f ~/.zshrc.local ]]; then
  source ~/.zshrc.local
fi
