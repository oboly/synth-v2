#!/usr/bin/env bash

# Shared terminal input helpers for local Synth setup scripts.
# This file must not contain secrets.
# Secret input is hidden while typing/pasting, then masked feedback is printed.
# This avoids leaking pasted secret fragments in terminal output.

read_secret_stars() {
    local prompt="$1"
    local var_name="$2"
    local input=""
    local old_stty=""

    printf "%s" "$prompt"

    old_stty="$(stty -g 2>/dev/null || true)"

    if [ -n "$old_stty" ]; then
        stty -echo
        trap 'stty "$old_stty" 2>/dev/null || true; trap - INT TERM RETURN' INT TERM RETURN
    fi

    IFS= read -r input

    if [ -n "$old_stty" ]; then
        stty "$old_stty" 2>/dev/null || true
        trap - INT TERM RETURN
    fi

    printf '\n'

    if [ -n "$input" ]; then
        printf "masked input: "
        printf "%*s" "${#input}" "" | tr ' ' '*'
        printf " length=%s\n" "${#input}"
    else
        printf "masked input: EMPTY length=0\n"
    fi

    printf -v "$var_name" '%s' "$input"
}

read_visible_value() {
    local prompt="$1"
    local var_name="$2"
    local input=""

    read -r -p "$prompt" input
    printf -v "$var_name" '%s' "$input"
}

print_value_length() {
    local label="$1"
    local value="$2"

    echo "${label} length: ${#value}"
}
