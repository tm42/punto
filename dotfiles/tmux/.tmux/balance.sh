#!/bin/zsh
# Give the current pane and its neighbour in $1 (L R U D) the same width (L/R)
# or height (U/D), leaving every pane outside that pair alone.
#
# tmux's own `select-layout even-horizontal` equalises every pane in the window.
# There is no built-in that balances one pair, which is the whole reason for this.
#
# Bound to M-e then h/j/k/l in ~/.tmux.conf, via the `balance` key table.

emulate -L zsh

dir=$1
case $dir in
  L) edge=pane_at_left   ;;
  R) edge=pane_at_right  ;;
  U) edge=pane_at_top    ;;
  D) edge=pane_at_bottom ;;
  *) exit 1 ;;
esac

# select-pane WRAPS at the window edge: from the leftmost pane, `select-pane -L`
# lands on the rightmost one. Without this guard a press at the edge silently
# resizes a pair on the far side of the window — it looks like it worked, because
# the numbers change. Measured on a three-pane row: from %0, -L lands on %2.
[[ $(tmux display -p "#{$edge}") == 1 ]] && exit 0

cur=$(tmux display -p '#{pane_id}')
tmux select-pane -$dir
nb=$(tmux display -p '#{pane_id}')
tmux select-pane -t "$cur"
[[ $nb == $cur ]] && exit 0

read -r cl ct cw ch <<< "$(tmux display -p -t "$cur" '#{pane_left} #{pane_top} #{pane_width} #{pane_height}')"
read -r nl nt nw nh <<< "$(tmux display -p -t "$nb"  '#{pane_left} #{pane_top} #{pane_width} #{pane_height}')"

# select-pane crosses levels of the layout tree, and resizing the pane it lands
# on then moves a different boundary. In a 2x2 grid beside one full-height pane,
# `-L` from the tall pane finds the grid's top-right cell, and resizing that cell
# moves the boundary inside the top row while the tall pane does not move at all.
# So the pair has to actually share the boundary about to move: abutting on this
# axis, and spanning the same extent on the other one. Refuse quietly otherwise,
# the way the edge guard above does.
#
# The divider occupies one cell, so a pane at left=0 width=74 ends at column 73
# and its neighbour starts at 75.
if [[ $dir == L || $dir == R ]]; then
  (( ct == nt && ch == nh )) || exit 0
  if (( cl < nl )); then
    (( cl + cw + 1 == nl )) || exit 0
    first=$cur
  else
    (( nl + nw + 1 == cl )) || exit 0
    first=$nb
  fi
  # Resize the left one of the pair: that moves the boundary between them and
  # nothing else. Resizing the right one is ambiguous about which edge moves.
  tmux resize-pane -t "$first" -x $(( (cw + nw) / 2 ))
else
  (( cl == nl && cw == nw )) || exit 0
  if (( ct < nt )); then
    (( ct + ch + 1 == nt )) || exit 0
    first=$cur
  else
    (( nt + nh + 1 == ct )) || exit 0
    first=$nb
  fi
  tmux resize-pane -t "$first" -y $(( (ch + nh) / 2 ))
fi
