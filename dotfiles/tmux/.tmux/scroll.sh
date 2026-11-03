#!/bin/sh
# Scroll a pane from the keyboard, whatever is running in it.
#
# An agent TUI (Claude Code, codex) draws on the alternate screen, so tmux keeps
# no scrollback for it and copy-mode sees only the visible screen. What such a
# pane does understand is a mouse-wheel report -- which is only bytes, so a key
# can send one. Anything else gets ordinary copy-mode scrolling instead.
#
#   scroll.sh <pane> up|down <lines|half|all>
#
# TMUXCMD exists so a test can aim this at a scratch server; a tmux key binding
# leaves it alone and the inherited $TMUX picks the right one.
set -eu
: "${TMUXCMD:=tmux}"

# One report per line scrolled, so a jump to the top is a thousand of them. A
# single write that size loses bytes in the pty input queue -- measured 1007 of
# 1015 arriving -- so send it in pieces the reader can drain between.
CHUNK=100
PAUSE=0.02

pane=$1
dir=$2
amount=${3:-1}

alt=$($TMUXCMD display -p -t "$pane" '#{alternate_on}')
in_mode=$($TMUXCMD display -p -t "$pane" '#{pane_in_mode}')

# Already in copy-mode, or an ordinary shell pane with real scrollback: scroll
# the way the prefix-less wheel binding does.
if [ "$in_mode" = 1 ] || [ "$alt" = 0 ]; then
    if [ "$in_mode" != 1 ]; then
        $TMUXCMD copy-mode -e -t "$pane"
    fi
    case "$dir:$amount" in
        # Leaving copy-mode is what puts the pane back on the live bottom and
        # keeps it there, which is what G has to mean.
        down:all)  $TMUXCMD send-keys -t "$pane" -X cancel; exit 0 ;;
        up:all)    key=history-top ;;
        up:half)   key=halfpage-up ;;
        down:half) key=halfpage-down ;;
        up:*)      key=scroll-up ;;
        down:*)    key=scroll-down ;;
    esac
    $TMUXCMD send-keys -t "$pane" -X "$key"
    exit 0
fi

btn=64
[ "$dir" = down ] && btn=65

height=$($TMUXCMD display -p -t "$pane" '#{pane_height}')
case $amount in
    half) n=$(( height / 2 )) ;;
    all)  n=1000 ;;              # past the top of any real session
    *)    n=$amount ;;
esac
[ "$n" -lt 1 ] && n=1

# SGR mouse report: ESC [ < <btn> ; <col> ; <row> M. Sent with -l as one literal
# string per chunk: -H takes a separate argument per byte, and tmux refuses the
# argv past about 70 reports with "command too long".
one=$(printf '\033[<%d;1;1M' "$btn")

sent=0
while [ "$sent" -lt "$n" ]; do
    burst=""
    i=0
    while [ "$i" -lt "$CHUNK" ] && [ "$sent" -lt "$n" ]; do
        burst="$burst$one"
        i=$(( i + 1 ))
        sent=$(( sent + 1 ))
    done
    $TMUXCMD send-keys -t "$pane" -l -- "$burst"
    if [ "$sent" -lt "$n" ]; then
        sleep "$PAUSE"
    fi
done
