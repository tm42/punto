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
# Only Homebrew's own directories and ~/.local/bin are added here. A tool this
# repo does not install — uv, bun, cargo, anything else — goes on PATH in
# machine.zsh, guarded by [ -d ], so a machine that lacks it carries no dead
# entry. ~/.local/bin is the one exception to that rule, and it is an exception
# because this repo does install something there: link.py puts the `punto`
# command in it.
typeset -U path PATH

# Guarded, because ~/.local/bin does not exist on a machine nothing has installed
# into yet. The guard runs once at startup, so the shell that ran the very first
# ./link.py does not carry the directory — that install needs a new shell before
# `punto` resolves, which is why INSTALL.md's link step says so.
[[ -d ~/.local/bin ]] && path=(~/.local/bin $path)

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
plugins=(git you-should-use zsh-bat)
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

# zsh-histdb: records commands to a SQLite database from zshaddhistory/precmd and
# leaves zsh's own history file alone, so the two stores are separate records of
# the same shell and ↑ below reads both.
# Not vendored here — INSTALL.md clones it into $HISTDB. Guarded on both the
# checkout and sqlite3, so a machine with neither loses only the ranked suggestion,
# the ^R widget below and ↑'s first tier, and reaches a normal prompt otherwise.
# sqlite-history.zsh installs no ZLE widget, so it goes ahead of this block.
# Overridable, because §2 sources ~/.config/punto/machine.zsh before this and a
# machine that keeps its clone elsewhere is exactly what that file is for. Upstream
# uses HISTDB_FILE, HISTDB_HOST and seven more, and no bare HISTDB, so the name is free.
HISTDB=${HISTDB:-~/.oh-my-zsh/custom/plugins/zsh-histdb}
# Must precede the source below — upstream PR #31.
[[ $OSTYPE == darwin* ]] && HISTDB_TABULATE_CMD=(sed -e $'s/\x1f/\t/g')
if [[ -f $HISTDB/sqlite-history.zsh ]] && (( $+commands[sqlite3] )); then
  source $HISTDB/sqlite-history.zsh
fi

# punto's ↑ and ↓. They sit here, between sqlite-history.zsh above and the
# plugins below, because zsh-autosuggestions lists both widget names in its
# ZSH_AUTOSUGGEST_CLEAR_WIDGETS (zsh-autosuggestions.zsh:61-62) and wraps them
# at load to clear the grey suggestion when either runs. Defining them after
# that source would clobber the wrapper and the suggestion would linger over a
# recalled command. That is the mirror of histdb-interactive.zsh at the end of
# §7, sourced after the plugins precisely so nothing wraps a widget that
# manages its own buffer.
#
# The names are oh-my-zsh's, reused rather than renamed, so the twelve bindkey
# lines it already ran (lib/key-bindings.zsh:38-40 and :42-44 for ↑, :51-53 and
# :55-57 for ↓ — emacs, viins and vicmd for the literal escape and again for
# the terminfo one) keep pointing here, and ↑ and ↓ cannot disagree about
# position depending on which escape the terminal sent. Guarded on
# _histdb_query like the block below, so without the clone or sqlite3 these
# stay oh-my-zsh's autoloaded functions, unmodified.
if (( $+functions[_histdb_query] )); then
  typeset -ga _punto_hist_list
  typeset -g  _punto_hist_prefix
  typeset -gi _punto_hist_index

  # Tier one: the distinct commands run in $PWD matching the prefix, newest
  # first. `group by commands.argv` and not (argv, dir) — the suggestion
  # strategy below groups by both because it wants one row per directory, and
  # here that would list one command once per directory it was ever run in.
  # Multi-line commands are left out, because _histdb_query returns rows
  # separated by newlines and one would arrive as fragments; $history still
  # reaches such a command in tier two, intact.
  _punto_histdb_local() {
    # % and _ are LIKE metacharacters and sql_escape does not touch them, so an
    # unescaped prefix like ec% would match more than what was typed.
    local prefix=$(sql_escape $1)
    prefix=${prefix//'%'/\\%}
    prefix=${prefix//_/\\_}
    local query="
        select commands.argv || char(30) from history
        left join commands on history.command_id = commands.rowid
        left join places on history.place_id = places.rowid
        where commands.argv LIKE '${prefix}%' ESCAPE '\'
          and places.dir = '$(sql_escape $PWD)'
          and instr(commands.argv, char(30)) = 0
        group by commands.argv
        order by max(history.start_time) desc
    "
    # Rows are terminated with 0x1e, not left on their own line, because a
    # command can contain a newline and sqlite3 separates rows with one — so a
    # multi-line command used to arrive as fragments, and the first fragment
    # matches the typed prefix, which would put half a command on the line for
    # Enter to run. 0x1e is excluded from the data above so the split cannot be
    # confused by it; nobody types one on purpose, where multi-line commands are
    # ordinary.
    #
    # `.mode list --escape off` is not optional. sqlite3's CLI renders control
    # characters in caret notation, so without it char(30) leaves as the two
    # bytes `^^` and no separator reaches the output at all: measured 2026-10-07,
    # `select 'A'||char(30)||'B'` gives 41 5e 5e 42 0a on /usr/bin/sqlite3 3.51.0
    # and Homebrew's 3.53.4, and 41 1e 42 0a with the mode set. Newline and tab
    # pass through raw either way, which is why the fault this fixes is real.
    #
    # Same two guards as the suggestion strategy below: _histdb_query echoes
    # "error in <the whole query>" on a non-zero sqlite3 exit
    # (sqlite-history.zsh:31) rather than returning a status, and sqlite3's own
    # stderr reaches the terminal regardless of that return value.
    local out=$(_histdb_query ".mode list --escape off" "$query" 2>/dev/null)
    [[ $out == error\ in* ]] && return 1
    print -r -- $out
  }

  # One list per sequence: tier one, then everything else matching from zsh's
  # own history by recency, with no entry repeated. Measured 2026-10-02 over
  # 2991 entries, the filter and dedupe cost 0.49 ms for a three-character
  # prefix, 1.41 ms for a single letter and 2.14 ms for an empty prefix —
  # monotone in the match count, so the empty prefix is the ceiling, and it is
  # paid once per sequence rather than on every press.
  _punto_hist_build() {
    local prefix=$1
    local -a local_hits global_hits rest
    # A database that exists but cannot be read is indistinguishable from no
    # local history here: tier one comes back empty and the walk degrades to
    # tier two alone, which is what ↑ did before this block existed.
    local out=$(_punto_histdb_local "$prefix")
    # Split on 0x1e, not on newlines, and strip the LEADING newline from each
    # element. sqlite3 writes the row's newline after the value, so after the
    # separator: the bytes for three rows are `one line 1e 0a multi 0a line two
    # 1e 0a three 0a four 0a five 1e 0a`, and every element but the first would
    # otherwise begin with a newline. That would survive into the ${a:|b}
    # subtraction below, which compares exact strings, so every local command
    # but the newest would appear twice in the walk. No empty-element handling
    # is needed: unquoted (s) splitting drops empty fields, so a prefix matching
    # nothing gives an array of length 0.
    [[ -n $out ]] && local_hits=( ${${(ps:\x1e:)out}##$'\n'} )
    # No (Oa): $history already expands newest-first, and reversing it would
    # make ↑ walk forward in time.
    #
    # And no (b) either. glob_subst is off, so the characters $prefix
    # contributes are never pattern metacharacters — only the * written here is
    # — which is exactly the literal match the .history-beginning-search-backward
    # this replaces performs. (b) would backslash-escape them, and since the
    # result is not pattern-expanded those backslashes become characters no
    # history entry contains: measured in zsh -f against
    # (git*log, git branch, gitxlog extra, git[a]b, gitzab x), the prefix git*
    # matches git*log and nothing else without (b), and matches nothing at all
    # with it — so (b) would silently break ↑ for any prefix holding *, [ or ?.
    global_hits=( ${(u)${(M)${history[@]}:#$prefix*}} )
    rest=( ${global_hits:|local_hits} )
    _punto_hist_list=( "${local_hits[@]}" "${rest[@]}" )
    _punto_hist_prefix=$prefix
    _punto_hist_index=0
  }

  # Index into that list, rebuilding when this press starts a new sequence or
  # the typed prefix has changed. Returns non-zero exactly where upstream's
  # .history-beginning-search-* would have failed, so the two widgets below
  # fall through as they did.
  _punto_hist_step() {
    local -i delta=$1 resume=$2
    local prefix=$LBUFFER
    if (( ! resume )) || [[ $_punto_hist_prefix != "$prefix" ]] ||
       (( ! $#_punto_hist_list )); then
      _punto_hist_build "$prefix"
    fi
    local -i next=$(( _punto_hist_index + delta ))
    (( next >= 1 && next <= $#_punto_hist_list )) || return 1
    _punto_hist_index=$next
    BUFFER=${_punto_hist_list[next]}
  }

  # oh-my-zsh's up-line-or-beginning-search with only
  # .history-beginning-search-backward replaced. All three branches stay: a
  # $LBUFFER holding a newline moves within the buffer, so with the cursor on
  # the first line of a multi-line buffer ↑ searches history instead; a
  # PREBUFFER with the edit-buffer zstyle pushes the line; only the third
  # branch searches. The $CURSOR restore is what makes $LBUFFER the typed
  # prefix again on a repeated press, which is how the step below knows the
  # sequence continues.
  up-line-or-beginning-search() {
    emulate -L zsh
    typeset -g __searching __savecursor
    local -i resume=0

    if [[ $LBUFFER == *$'\n'* ]]; then
      zle .up-line-or-history
      __searching=''
    elif [[ -n $PREBUFFER ]] &&
        zstyle -t ':zle:up-line-or-beginning-search' edit-buffer
    then
      zle .push-line-or-edit
    else
      [[ $LASTWIDGET = $__searching ]] && { CURSOR=$__savecursor; resume=1 }
      __savecursor=$CURSOR
      __searching=$WIDGET
      _punto_hist_step 1 $resume
      zstyle -T ':zle:up-line-or-beginning-search' leave-cursor &&
          zle .end-of-line
    fi
  }
  zle -N up-line-or-beginning-search

  # oh-my-zsh's down-line-or-beginning-search with only
  # .history-beginning-search-forward replaced. The $NUMERIC and $RBUFFER tests
  # and the fall-through to .down-line-or-history stay, so ↓ leaves the walk
  # the same way it did when the search ran off the newest end.
  down-line-or-beginning-search() {
    emulate -L zsh
    typeset -g __searching __savecursor
    local -i resume=0

    if [[ ${+NUMERIC} -eq 0 &&
        ( $LASTWIDGET = $__searching || $RBUFFER != *$'\n'* ) ]]
    then
      [[ $LASTWIDGET = $__searching ]] && { CURSOR=$__savecursor; resume=1 }
      __searching=$WIDGET
      __savecursor=$CURSOR
      if _punto_hist_step -1 $resume; then
        [[ $RBUFFER = *$'\n'* ]] ||
            zstyle -T ':zle:down-line-or-beginning-search' leave-cursor &&
            zle .end-of-line
        return
      fi
      [[ $RBUFFER = *$'\n'* ]] || return
    fi
    __searching=''
    zle .down-line-or-history
  }
  zle -N down-line-or-beginning-search
fi

if [[ -n $BREW_PREFIX ]]; then
  for _f in fzf-tab/fzf-tab.zsh \
            zsh-autosuggestions/zsh-autosuggestions.zsh \
            zsh-syntax-highlighting/zsh-syntax-highlighting.zsh; do
    [[ -f $BREW_PREFIX/share/$_f ]] && source $BREW_PREFIX/share/$_f
  done
  unset _f
fi
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=245'

# histdb-interactive.zsh installs a ZLE widget of its own, one that manages its own
# buffer and redisplay, so it sits after this block rather than inside it — neither
# zsh-autosuggestions nor zsh-syntax-highlighting above gets to wrap it. Guarded on
# _histdb_query, which is defined only when the source above succeeded.
if (( $+functions[_histdb_query] )); then
  # README's second strategy: an exact match in this directory first, falling
  # back to the most frequent command anywhere so it never goes silent. No
  # longer upstream's text verbatim, which histdb-suggestions recorded that it
  # was — the error guard and the wildcard escaping below both depart from it.
  _zsh_autosuggest_strategy_histdb_top() {
      # % and _ are LIKE metacharacters and sql_escape does not touch them, so
      # an unescaped prefix like ec% would offer echo dup instead of matching
      # what was actually typed.
      local prefix=$(sql_escape $1)
      prefix=${prefix//'%'/\\%}
      prefix=${prefix//_/\\_}
      local query="
          select commands.argv from history
          left join commands on history.command_id = commands.rowid
          left join places on history.place_id = places.rowid
          where commands.argv LIKE '${prefix}%' ESCAPE '\'
          group by commands.argv, places.dir
          order by places.dir != '$(sql_escape $PWD)', count(*) desc
          limit 1
      "
      # _histdb_query echoes "error in <the whole query>" on a non-zero sqlite3
      # exit (sqlite-history.zsh:31) rather than returning a status, and
      # sqlite3's own stderr reaches the terminal regardless of that return
      # value — so the redirect below stops a failing query painting its error
      # onto the prompt line as you type, and the test stops that error text
      # being offered back as the suggestion itself.
      suggestion=$(_histdb_query "$query" 2>/dev/null)
      [[ $suggestion == error\ in* ]] && suggestion=""
  }
  ZSH_AUTOSUGGEST_STRATEGY=(histdb_top)
  source $HISTDB/histdb-interactive.zsh
  bindkey '^r' _histdb-isearch
fi

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
