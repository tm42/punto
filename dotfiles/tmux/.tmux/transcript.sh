#!/bin/sh
# Open an agent session as searchable plain text.
#
# Neither Claude Code nor codex can search its own output, and both draw on the
# alternate screen, so tmux copy-mode only ever sees the visible screen. Both do
# keep the whole session as JSONL on disk, which is what this reads.
#
#   transcript.sh <pane>
#
# The tool is read from the pane's command and only codex is recognised by name,
# so a shell pane is read as Claude Code and gets the newest session for its own
# directory. The rendered text names the file it came from on its first line,
# which is the only thing that tells the two apart.
set -eu
: "${TMUXCMD:=tmux}"
here=$(cd "$(dirname "$0")" && pwd)

# The pane is an argument so this is callable by hand, but the key binding cannot
# supply one: display-popup does not expand #{...} in its shell-command, though
# run-shell does, so the argument arrives as the literal string `#{pane_id}`. Taking
# it on trust is what made M-/ a popup that opened and closed with no message, since
# the first read below then fails under set -e. Inside a popup the client's active
# pane is still the one the key was pressed in, which is the pane wanted here.
pane=${1:-}
case $pane in
    %[0-9]*) ;;
    *)       pane=$($TMUXCMD display -p '#{pane_id}') ;;
esac

cmd=$($TMUXCMD display -p -t "$pane" '#{pane_current_command}')
cwd=$($TMUXCMD display -p -t "$pane" '#{pane_current_path}')

case $cmd in
    *codex*) tool=codex ;;
    *)       tool=claude ;;      # Claude Code's pane command is its version string
esac

out=$(mktemp -t "transcript-$tool")

# A trap and not a trailing rm: set -eu is on, so any non-zero exit from nvim ends
# the script where it stands and leaves the whole rendered session in $TMPDIR. :cq
# exits 1, a machine without nvim exits 127, and killing the popup's pane skips a
# trailing rm altogether.
trap 'rm -f "$out"' EXIT INT TERM

if ! err=$(/usr/bin/python3 "$here/transcript.py" "$tool" "$cwd" 2>&1 >"$out"); then
    # The key binding runs this inside display-popup -E, which closes the moment
    # the command exits, so stderr reaches nobody at all. tmux's message line is
    # the one surface that outlives the popup.
    #
    # display-message takes a format string, and tmux runs `#(command)` in one, so
    # the message has to be escaped before it is handed over: the text carries the
    # pane's own path, and a directory named `#(...)` would otherwise execute. `##`
    # is a literal `#` to tmux, and escaping that one character is enough because
    # it is the only metacharacter a format has. `display-message -l` would also do
    # it and needs tmux 3.2, where this repository's floor is 3.0.
    msg=$(printf '%s' "transcript: ${err:-no $tool session log found}" | sed 's/#/##/g')
    $TMUXCMD display-message "$msg"
    exit 1
fi

# normal G starts at the newest line, so ? searches backwards through the session.
#
# setlocal and not set: `set` on a buffer-local option also moves the global default,
# so every new buffer in this nvim would be unmodifiable too and any plugin writing a
# scratch buffer fails. :LualineNotices did, with E21 out of appendbufline.
nvim -R -c 'setlocal nomodifiable' -c 'normal G' "$out"
