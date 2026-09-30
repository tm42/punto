#!/bin/zsh
# Coding-agent hook → tmux pane state + status strip + optional macOS notification.
#
# One script, three agents. The agent name is argument 1 and is used only for the
# label, because all three deliver the same hook payload: a JSON object on stdin
# carrying .hook_event_name and .cwd, from a command named in
#   ~/.claude/settings.json   UserPromptSubmit, PermissionRequest, Notification, Stop
#   ~/.codex/hooks.json       PermissionRequest, Stop
# opencode has no hooks file and reaches this script from a plugin instead —
# ~/.config/opencode/plugins/tmux-agent.ts, which builds the same JSON from the
# event bus and pipes it in. UserPromptSubmit, PermissionRequest, Stop.
# The one difference is that Codex's PermissionRequest has no .message — it
# carries .tool_name and .tool_input.description instead.
#
# ── What @agent_state is for ────────────────────────────────────────────────
# .tmux.conf renders a pane's state as "<State> | <name>", in Codex's own words,
# for both agents. Codex publishes those words in its pane title and needs no
# help; Claude publishes a constant "✳ <session>" that never changes, not even
# while it is working, so every state Claude has comes from here.
#
#   working   a turn started. Claude and opencode — Codex's title says Working
#             itself.
#   wait      blocked on you, from PermissionRequest. Codex says "Action
#             Required" in its title too, so this is Claude's only source and
#             Codex's backstop.
#   ready     a turn ended, or the agent has been waiting on you long enough to
#             say so. BOTH agents need this: Codex's title reports Ready for a
#             finished turn and for a pane untouched since yesterday alike, so
#             the title cannot tell you a question is waiting.
#   unset     nothing pending. .tmux.conf clears `ready` when you visit the
#             pane; `wait` survives, because an approval you have looked at and
#             not answered is still an approval.
#
# Notification is deliberately NOT wait, and from Claude raises no notice. Claude fires
# it both for a permission prompt and after sitting idle >=60s, and the second is
# the opposite of blocked on you — it is precisely ready. Mapping both to wait
# pinned every Claude pane you walked away from to "Action Required" forever,
# since visiting never clears wait. PermissionRequest is the event that means only the one thing, so wait
# comes from there; Notification then declines to downgrade an existing wait,
# because Claude fires it 60s into a prompt that is still pending.
#
# ── The notification ────────────────────────────────────────────────────────
# The tmux status strip fires only when the agent's pane is in the background —
# if you're looking at it you already know. Always exits 0: a hook that errors
# would nag the agent, not you.
#
#   AGENT_NOTIFY_BANNER  non-empty to also raise a macOS notification. Unset = no
#                        banner, which also means no notification at all outside
#                        tmux. INSTALL.md step 7 suggests where to export it.
#   AGENT_NOTIFY_SOUND   alert sound for that banner, or "" for silent (default
#                        Submarine). No effect while the banner is off.

emulate -L zsh
zmodload zsh/datetime
setopt no_unset extended_glob     # extended_glob: the ##pattern strip below needs it
exec 2>/dev/null

agent=${1:-claude}
soft=''      # set by Notification only: never overwrite a pending wait
payload=$(cat)
event=$(printf '%s' "$payload" | jq -r '.hook_event_name // "Stop"')
cwd=$(printf '%s' "$payload" | jq -r '.cwd // ""')

case $event in
  # Claude puts the reason in .message. Codex has none on PermissionRequest, so
  # fall back to the tool description and then to the tool name — "waiting for
  # input" is true but tells you nothing about whether it is worth switching to.
  PermissionRequest|Notification)
    verb=$(printf '%s' "$payload" | jq -r '
      .message // .tool_input.description // .tool_name // "waiting for input"')
    if [[ $event == PermissionRequest ]]; then
      state=wait; glyph='◆'
    else
      state=ready; soft=1
      # Claude's Notification is the one event that fires because nothing happened,
      # which is why it is the only one that can repeat while you do nothing.
      # Measured: a turn ended at 19:31:19, its notice aged out at the 30s HOLD, and
      # at 19:32:19 — 60s to the second — Notification raised a fresh "◆ Claude is
      # waiting for your input" on the same pane with a new @notice_at, on a turn
      # that had already finished and been read. An empty glyph is this file's
      # existing way to say "not news": it exits before the notice and before the
      # banner, leaving the soft `ready` below. Nothing is lost, because Claude
      # declares PermissionRequest too and that is the event that means it is
      # actually blocked on you.
      #
      # Claude and no one else, because both halves of that argument are about
      # Claude: its 60s idle timer, and its declaring PermissionRequest as well. An
      # agent that sends this name for something that IS news would be silenced
      # outright, and silently — every unrecognised event still reaches the bar
      # through the fallback below, so this branch would be the only way to
      # disappear. Anything but Claude keeps the ◆ it had.
      if [[ $agent == claude ]]; then glyph=''; else glyph='◆'; fi
    fi ;;
  UserPromptSubmit) state=working; glyph=''  ; verb='working' ;;
  Stop)             state=ready;   glyph='✳' ; verb='finished' ;;
  *)                state='';      glyph='·' ; verb=$event ;;
esac

name=${cwd:t}

# Which pane is this hook about? tmux exports TMUX_PANE into everything it
# spawns, so an agent started in a pane inherits it and hands it to the hook.
# Not always: on one machine Claude runs with neither TMUX nor TMUX_PANE in its
# environment while `list-panes` shows it as that pane's own current command —
# plain binary, no wrapper, launched from the pane's shell — so every hook it
# fired was dropped on this line and the pane's state froze at whatever it last
# was. The pane still owns the process, so ask the process tree when the
# variable is missing: walk up from this script until a pid is some pane's
# pane_pid. The real chain is hook -> agent -> pane shell, three hops.
#
# Costs one `list-panes` and a few `ps` calls, and only on the fallback. With no
# $TMUX the tmux calls resolve the default socket, which is the only one they
# could have been about.
pane=${TMUX_PANE:-}
if [[ -z $pane ]]; then
  typeset -A pane_of
  while read -r ppid pid; do pane_of[$ppid]=$pid; done < <(
    tmux list-panes -a -F '#{pane_pid} #{pane_id}')
  p=$$
  for _ in {1..12}; do
    [[ -n ${pane_of[$p]:-} ]] && { pane=${pane_of[$p]}; break }
    p=${${$(ps -o ppid= -p $p)}// /}
    [[ -n $p ]] && (( p > 1 )) || break
  done
fi

if [[ -n $pane ]]; then
  # session_attached, not just pane_active and window_active: those two say the
  # pane is the current one *within its own session*, which is true of every
  # pane in a session nobody is looking at. Without it, detaching and leaving an
  # agent running made Stop clear the state instead of setting ready — the exact
  # case ready exists for.
  # @agent_state is deliberately not in this format. #{@agent_state} walks pane,
  # window, session, global, so a value set globally reads as present on every
  # pane — and the one test that consults it below would then be true
  # everywhere. It is read at pane scope instead, inside that test, because that
  # is the only branch that wants it: a hook event fires from three agents in
  # every pane, and a second tmux call on all of them to serve one branch is a
  # cost this path cannot carry.
  info=$(tmux display -p -t "$pane" \
        '#{&&:#{session_attached},#{&&:#{pane_active},#{window_active}}}|#I.#P|#{pane_title}')
  fg=${info%%|*}
  # A stale pane id is not an error to tmux 3.7c: it exits 0 and expands the
  # format against empty fields, so testing the field beats testing the string.
  [[ $fg == [01] ]] || exit 0

  rest=${info#*|}; idx=${rest%%|*}
  # The title is last and takes the whole remainder, because a pane title can
  # itself contain "|" — "Action Required | punto-wk" is one this repo writes.
  title=${rest#*|}

  # `ready` means "finished and unread", so a turn that ends while you are
  # looking at the pane has already been read: clear it rather than set it.
  #
  # $soft is Notification and nothing else. Claude fires it 60s into an approval
  # that is still pending, so it must not overwrite a `wait` — but Stop must,
  # or granting an approval leaves the pane reading "Action Required" for good.
  #
  # `show -pv`, not the format above: it exits 1 rather than inheriting, so a
  # global @agent_state of `wait` cannot suppress this on a pane that holds no
  # state of its own. The value is compared and not the exit status, because a
  # pane owning an explicitly empty @agent_state exits 0 with no output and is
  # not a pending approval either. Claude is the only agent here whose wiring
  # declares Notification, so it is the only one that reaches this branch at
  # all — codex's and opencode's Stop goes straight to the arms below.
  if [[ -n $soft ]] && \
     [[ $(tmux show -pv -t "$pane" @agent_state 2>/dev/null) == wait ]]; then
    :
  elif [[ $state == ready && $fg == 1 ]]; then
    tmux set -pu -t "$pane" @agent_state
  elif [[ -n $state ]]; then
    tmux set -p -t "$pane" @agent_state "$state"
  fi
  tmux refresh-client -S

  [[ -n $glyph ]] || exit 0               # a prompt you just typed is not news

  # Both agents put decoration in the pane title; only the name is worth showing.
  # Claude prefixes ✳ and nothing else — its title never changes, so the spinner
  # frames an earlier version of this script stripped for do not exist. Codex
  # prefixes its run-state and, if `activity` is configured, a blinker ahead of
  # that; the [^|]* in the second strip covers whatever that blinker renders as.
  title=${title##✳[[:space:]]#}
  title=${title##(#b)*(Ready|Working|Action Required)[[:space:]]#\|[[:space:]]#}
  # opencode prefixes its session with "OC | " and publishes a bare "OpenCode"
  # until the session has one, so the second is dropped and the .cwd basename
  # stands in for it — the same split ~/.tmux.conf makes for the tab, so the tab
  # and the notice never disagree about what a pane is called.
  if [[ $agent == opencode ]]; then
    [[ $title == 'OC | '* ]] && title=${title#'OC | '} || title=''
  fi
  [[ -n $title ]] && name=$title

  # Not display-message; see the header of status-tick.sh. Pane-scoped rather
  # than global, because a single global slot meant the second of two agents
  # finishing at once erased the first with nothing to say it had. The pane that
  # owns the option is also the pane whose arrival clears it, so there is no
  # separate @notice_pane to keep in step.
  if [[ $fg == 0 ]]; then
    # Four hazards, all of them the status bar's rather than a message's, so both
    # escapes live in here with the only two things that read them. '#' introduces
    # a format, and both halves reach the bar: the verb from the agent, the name
    # from the pane title. A newline is worse than it looks — tmux keeps only the
    # LAST line of a #() job's output, so one newline in a Codex tool description
    # drops the glyph, the agent, the window and the name, and the highlight with
    # them. '|' is the field separator status-tick.sh reads these back with, and a
    # Codex tool description is free to contain one; it becomes '/' rather than
    # being deleted, which reads like a typo and is not one. And the caps keep the
    # whole notice inside the 85 cells that status-right has left after git, the
    # clock and the date; nothing else trims it, and tmux trims from the right, so
    # an uncapped name eats the clock.
    # $name itself stays clean: the macOS banner is not a tmux format.
    esc=${${${${verb//$'\n'/ }//\#/\#\#}//\|//}:0:40}
    nesc=${${${${name//$'\n'/ }//\#/\#\#}//\|//}:0:20}
    tmux set -p -t "$pane" @notice_txt " $glyph  $agent w$idx  $nesc — $esc " \; \
         set -p -t "$pane" @notice_name "$nesc" \; \
         set -p -t "$pane" @notice_glyph "$glyph" \; \
         set -p -t "$pane" @notice_at "$EPOCHSECONDS" \; \
         refresh-client -S
  fi
fi

[[ -n ${AGENT_NOTIFY_BANNER:-} ]] || exit 0
[[ -n $glyph ]] || exit 0

# A visible pane earns no status notice — you would be looking at the bar as it
# appeared. It still earns a banner whenever the terminal itself is not the
# frontmost application, which is the case the old single `$fg == 1` exit
# swallowed: the pane open, your eyes on another app, and nothing anywhere to
# tell you. lsappinfo ships with macOS and needs no Automation permission,
# unlike asking System Events for the frontmost process; measured at 9ms a call,
# and only ever on this path.
#
# NOT $TERM_PROGRAM. tmux has overwritten it with "tmux" in every pane it spawns
# since 3.2, and this gate only ever runs inside tmux, so the pattern was "tmux",
# never matched "iTerm2", and silenced nothing: with the banner on, every turn
# you sat and watched raised one. The server's own environment still holds what
# the client that started it had. It goes stale if you later attach from a
# different terminal application, which is what AGENT_NOTIFY_APP is for.
#
# The names then have to be reconciled, because none of the three sources agree:
# TERM_PROGRAM says "iTerm.app" and "Apple_Terminal" where lsappinfo says "iTerm2"
# and "Terminal". Stripping ".app" and a leading "Apple_" covers both, and the
# match is a case-insensitive substring rather than an equality. Anything else —
# VS Code calls itself "vscode" and shows as "Code" — needs AGENT_NOTIFY_APP.
# An empty pattern raises the banner rather than silencing it, because a banner
# too many is cheaper than one you needed.
if [[ ${fg:-0} == 1 ]]; then
  app=${AGENT_NOTIFY_APP:-$(tmux show-environment -g TERM_PROGRAM)}
  app=${app#TERM_PROGRAM=}; app=${app%.app}; app=${app#Apple_}
  if [[ -n $app && $app != tmux ]]; then
    front=$(lsappinfo info -only name "$(lsappinfo front)")
    [[ $front == *(#i)${app}* ]] && exit 0
  fi
fi

sound=${AGENT_NOTIFY_SOUND-Submarine}
if [[ -n $sound ]]; then
  osascript -e 'on run {t, s, m, snd}' \
            -e 'display notification m with title t subtitle s sound name snd' \
            -e 'end run' -- "$agent" "$name" "$verb" "$sound"
else
  osascript -e 'on run {t, s, m}' \
            -e 'display notification m with title t subtitle s' \
            -e 'end run' -- "$agent" "$name" "$verb"
fi

exit 0
