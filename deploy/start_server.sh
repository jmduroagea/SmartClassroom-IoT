#!/usr/bin/env bash
# Starts the three programs of the Server Pi (brain, web, emergency centre) in one
# tmux session, one window each, so a single command replaces three terminals (#46).
#
#     ./deploy/start_server.sh          # start them and show them (or show them again)
#     ./deploy/start_server.sh stop     # stop all three
#
# They keep running if the SSH connection drops: run the script again to see them.
# Inside tmux: Ctrl+B then 0, 1 or 2 changes window; Ctrl+B then D leaves them running.
# A program that stops keeps its window open, so its last lines can still be read.
set -eu

SESSION="smartroom"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$REPO_DIR/deploy/run.sh"
PROGRAMS=(brain web emergency)   # window 0, 1 and 2, in this order

# What each window runs: the program, and when it stops, a pause, so its last
# lines (the error, if it crashed) stay on screen until Enter is pressed.
window_command() {
  echo "$RUN $1; echo; echo '$1 stopped. Press Enter to close this window.'; read -r _"
}

if ! command -v tmux > /dev/null; then
  echo "tmux is not installed: sudo apt-get install -y tmux"
  exit 1
fi

case "${1:-start}" in
  start)
    if tmux has-session -t "$SESSION" 2> /dev/null; then
      echo "Already running."
    else
      tmux new-session -d -s "$SESSION" -n "${PROGRAMS[0]}" "$(window_command "${PROGRAMS[0]}")"
      for program in "${PROGRAMS[@]:1}"; do
        tmux new-window -t "$SESSION" -n "$program" "$(window_command "$program")"
      done
      tmux select-window -t "$SESSION:0"
      echo "Started: ${PROGRAMS[*]}"
    fi
    exec tmux attach -t "$SESSION"
    ;;
  stop)
    if tmux kill-session -t "$SESSION" 2> /dev/null; then
      echo "Stopped: ${PROGRAMS[*]}"
    else
      echo "Nothing was running."
    fi
    ;;
  *)
    echo "usage: $0 [start|stop]"
    exit 2
    ;;
esac
