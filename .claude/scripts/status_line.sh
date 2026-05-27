#!/bin/bash
# Claude Code statusLine script
# Displays: directory (blue), git info, session time, context usage, lines changed, cost

input=$(cat)

# Parse JSON input
cwd=$(echo "$input" | jq -r '.workspace.current_dir')
duration_ms=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
lines_added=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
lines_removed=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
total_cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
model=$(echo "$input" | jq -r '.model.display_name // "Claude"')
usage=$(echo "$input" | jq '.context_window.current_usage')

# Calculate context percentage
if [ "$usage" != "null" ]; then
    current_input=$(echo "$usage" | jq -r '.input_tokens // 0')
    cache_creation=$(echo "$usage" | jq -r '.cache_creation_input_tokens // 0')
    cache_read=$(echo "$usage" | jq -r '.cache_read_input_tokens // 0')
    current_tokens=$((current_input + cache_creation + cache_read))
    context_window_size=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
    context_pct=$((current_tokens * 100 / context_window_size))
    context_display="${context_pct}%"
else
    context_display='0%'
fi

# Convert milliseconds to seconds for duration
session_seconds=$((duration_ms / 1000))

# Format session duration
if [ "$session_seconds" -ge 3600 ]; then
    hours=$((session_seconds / 3600))
    minutes=$(((session_seconds % 3600) / 60))
    seconds=$((session_seconds % 60))
    duration_display=$(printf '%d:%02d:%02d' "$hours" "$minutes" "$seconds")
elif [ "$session_seconds" -ge 60 ]; then
    minutes=$((session_seconds / 60))
    seconds=$((session_seconds % 60))
    duration_display=$(printf '%d:%02d' "$minutes" "$seconds")
else
    duration_display=$(printf '0:%02d' "$session_seconds")
fi

# Format cost
cost_display=$(printf '$%.4f' "$total_cost")

# Change to working directory
cd "$cwd" 2>/dev/null || exit 0

# Get directory name
dir=$(basename "$cwd")

# Colors
BLUE='\033[38;2;65;146;216m'
RESET='\033[0m'

# Check if git repo and build output
if git rev-parse --git-dir > /dev/null 2>&1; then
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

    # Check for uncommitted changes
    dirty=''
    git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null || dirty='*'

    # Check for stashes
    stash=''
    git rev-parse --verify refs/stash >/dev/null 2>&1 && stash='≡'

    printf "${BLUE}%s${RESET} %s%s%s │ %s │ %s │ %s ctx │ +%s -%s │ %s" \
        "$dir" "$branch" "$dirty" "$stash" "$model" "$duration_display" "$context_display" "$lines_added" "$lines_removed" "$cost_display"
else
    printf "${BLUE}%s${RESET} │ %s │ %s │ %s ctx │ +%s -%s │ %s" \
        "$dir" "$model" "$duration_display" "$context_display" "$lines_added" "$lines_removed" "$cost_display"
fi
