# tmux pane status — publishes @ps_state / @ps_cmd / @ps_code / @ps_dur as tmux pane options.
# Rendered by window-status-format + pane-border-format in ~/.tmux.conf.
# Source from ~/.zshrc. Safe to source outside tmux (no-op).

[[ -n $TMUX ]] || return 0

autoload -Uz add-zsh-hook
zmodload zsh/datetime          # $EPOCHREALTIME — sub-second, monotonic enough here

typeset -g _ps_running=0
typeset -gF _ps_start=0

# 84ms / 2.4s / 47s / 3m08s / 1h04m — narrow enough for a pane border at any width.
# Sub-second gets milliseconds rather than a useless "0.0s": most commands you run
# are fast, and those are exactly the ones that would otherwise show nothing.
_ps_fmt() {
  local -F t=$1
  local -i s=$t
  if   (( t < 1 ));    then printf '%dms' $(( t * 1000 ))
  elif (( t < 10 ));   then printf '%.1fs' $t
  elif (( s < 60 ));   then printf '%ds' $s
  elif (( s < 3600 )); then printf '%dm%02ds' $((s/60)) $((s%60))
  else                      printf '%dh%02dm' $((s/3600)) $(((s%3600)/60))
  fi
}

_ps_preexec() {
  _ps_running=1
  _ps_start=$EPOCHREALTIME
  # newlines collapsed so a heredoc/multiline command can't wreck the status line
  tmux set -p -t "$TMUX_PANE" @ps_cmd "${1//$'\n'/ }" \; \
       set -p -t "$TMUX_PANE" @ps_state run \; \
       set -pu -t "$TMUX_PANE" @ps_dur \; \
       refresh-client -S 2>/dev/null
}

_ps_precmd() {
  local code=$?
  (( _ps_running )) || return 0   # bare Enter or shell startup — no command ran
  _ps_running=0

  local -F elapsed=$(( EPOCHREALTIME - _ps_start ))
  local dur=$(_ps_fmt $elapsed)
  local state=ok
  (( code )) && state=err

  # ✔/✘ is an acknowledgement the pane is owed, and a pane you were watching when
  # the command finished has already been acknowledged. Only the after-select-pane
  # hook in ~/.tmux.conf ever cleared it, and that fires on arrival, so a command
  # run in the pane you never left sat in the tab as "✔ ls" until you switched away
  # and came back. Same foreground test as agent-notify.sh and status-tick.sh,
  # session_attached and all: the current pane of a session nobody is attached to
  # is being read by nobody. `if -F` rather than a second `tmux display` keeps this to one tmux
  # call; -t is required, or the format expands against the calling client's pane
  # instead of this one. @ps_code and @ps_dur are set either way, because
  # pane-border-format reads those and not @ps_state — the border still says
  # "✔ ls  84ms" for the command you just watched.
  tmux set -p -t "$TMUX_PANE" @ps_code "$code" \; \
       set -p -t "$TMUX_PANE" @ps_dur "$dur" \; \
       if -F -t "$TMUX_PANE" '#{&&:#{session_attached},#{&&:#{pane_active},#{window_active}}}' \
          "set -pu -t $TMUX_PANE @ps_state" \
          "set -p -t $TMUX_PANE @ps_state $state" \; \
       refresh-client -S 2>/dev/null
}

add-zsh-hook preexec _ps_preexec
add-zsh-hook precmd  _ps_precmd
