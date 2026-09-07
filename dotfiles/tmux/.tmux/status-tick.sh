#!/bin/zsh
# Status-bar housekeeping, run from status-right. tmux re-expands that on every
# redraw, so this runs on the status-interval tick and again within about 20ms
# of any pane, window or session switch. That switch-driven run still sees the
# frame before the switch, so a notice whose pane you have just reached goes on
# the tick after it: 2.0s measured at status-interval 5, and bounded by it. No
# hook pushes it — one measured against this cost seven lines and a second
# concurrent sweep per switch, to save at most those two seconds.
#
# THE NOTICE replaces `display-message`, whose timeout tmux cancels on the next
# key you press: a Stop in window 4 vanished because you kept typing in window 1.
# This one lives in the bar, so only its own pane coming into view clears it —
# or HOLD seconds passing. Notices are pane-scoped options, so several can be
# pending at once; past one they collapse to a count and a list of names, which
# is the only shape that fits on a line already holding git, the clock and the
# date.
#
# THE SWEEP retires a "Working" its pane has outlived. State is latched by hooks,
# and Claude fires none when you interrupt a turn with Esc or when it is killed,
# so the latch outlives the turn with nothing to clear it. What separates the two
# is that a working pane redraws: measured on 2.1.252 against a real turn, no two
# consecutive 3s samples of the screen were identical while it streamed, and the
# screen then held one value for the 50s after Esc. FREEZE is ten times that 3s
# sampling floor, so the cost of being wrong is a tab that reads Working for half
# a minute too long rather than one that goes quiet mid-turn.
#
# Nothing filters on the pane's command, and testing it would be a bug: a killed
# agent leaves the pane back at zsh, which is exactly the case with no hook to
# clear it. No filter is needed either — Codex declares only PermissionRequest
# and Stop, so `working` is Claude's alone.
#
# Both refresh the client only when they changed something, so the redraw that
# causes finds nothing to do and stops there.
emulate -L zsh
zmodload zsh/datetime

HOLD=30     # seconds a notice survives if you never visit its pane
FREEZE=30   # seconds of an unchanging screen before "Working" is retired

# Every pending notice, gathered from the panes that own them. Read through a
# process substitution rather than a pipe, because zsh runs every stage of a
# pipeline in a subshell and $pending would not survive the loop.
typeset -a pending
single=''
while IFS='|' read -r id nat ntxt nname nglyph; do
  # @notice_txt with no @notice_at renders nowhere and ages out of nothing: the pane
  # never joins $pending, so neither clear below reaches it and the fragment stays set
  # for the life of the pane. Nothing is known to produce that state — the notifier sets
  # all four options in one chain — so this is a floor under the option rather than a fix
  # for a caller. No refresh-client, because nothing was on screen to redraw.
  if [[ -z $nat ]]; then
    [[ -n $ntxt || -n $nname || -n $nglyph ]] &&
      tmux set -pu -t "$id" @notice_txt \; set -pu -t "$id" @notice_name \; set -pu -t "$id" @notice_glyph
    continue
  fi
  # The notifier's own foreground test: current pane, current window, and a
  # client attached to that session.
  seen=$(tmux display -p -t "$id" \
        '#{&&:#{session_attached},#{&&:#{pane_active},#{window_active}}}' 2>/dev/null)
  if (( EPOCHSECONDS - nat >= HOLD )) || [[ $seen == 1 ]]; then
    tmux set -pu -t "$id" @notice_txt \; set -pu -t "$id" @notice_name \; \
         set -pu -t "$id" @notice_glyph \; set -pu -t "$id" @notice_at \; refresh-client -S
    continue
  fi
  pending+=("$nat|$nname|$nglyph")
  single=$ntxt
done < <(tmux list-panes -a \
         -F '#{pane_id}|#{@notice_at}|#{@notice_txt}|#{@notice_name}|#{@notice_glyph}' 2>/dev/null)

notice=''
if (( ${#pending} == 1 )); then
  notice=$single
elif (( ${#pending} > 1 )); then
  # Newest first, and ◆ outranks ✳: one pane blocked on you matters more than
  # two that merely finished, and taking the last hook's glyph would let a Stop
  # mask a pending approval. The verb goes away with the collapse — three of
  # them will not fit beside git, the clock and the date, and the count is the
  # news. One cap on the joined list, since the per-name cap that ends at the
  # right width for one name is three times too wide for three.
  # A name is empty when the payload carried no .cwd and the title stripped to
  # nothing; it would print as a dangling ", " and a count that no longer matches
  # what you can read.
  typeset -a names
  glyph='✳'
  for e in ${(On)pending}; do
    rest=${e#*|}; [[ -n ${rest%|*} ]] && names+=("${rest%|*}")
    [[ ${e##*|} == '◆' ]] && glyph='◆'
  done
  # Counted from the names rather than from $pending, so the number always
  # matches what you can read. A dropped empty name would otherwise leave
  # "3 agents" beside two of them.
  if (( ${#names} )); then
    list=${(j:, :)names}
    (( ${#list} > 46 )) && list="${list[1,45]}…"
    notice=" $glyph  ${#names} agents  ·  $list "
  else
    notice=" $glyph  ${#pending} agents "
  fi
fi

tmux list-panes -a -F '#{pane_id} #{@agent_state} #{@agent_screen} #{@agent_screen_at}' 2>/dev/null |
while read -r id state hash hash_at; do
  [[ $state == working ]] || continue
  now=$(tmux capture-pane -p -t "$id" 2>/dev/null | cksum | cut -d' ' -f1)
  if [[ $now != $hash ]]; then
    tmux set -p -t "$id" @agent_screen "$now" \; set -p -t "$id" @agent_screen_at "$EPOCHSECONDS"
  elif (( EPOCHSECONDS - ${hash_at:-EPOCHSECONDS} >= FREEZE )); then
    tmux set -pu -t "$id" @agent_state \; set -pu -t "$id" @agent_screen \; \
         set -pu -t "$id" @agent_screen_at \; refresh-client -S
  fi
done

[[ -n $notice ]] && print -rn -- "#[bg=#e0af68,fg=#1a1b26,bold]$notice#[bg=#24283b,fg=#565f89] "
exit 0
