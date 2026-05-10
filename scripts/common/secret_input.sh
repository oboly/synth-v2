#!/usr/bin/env bash

# Shared terminal input helpers for local Synth setup scripts.
# This file must not contain secrets.
# Use visible prompts or star-masked prompts; avoid fully silent input.

read_secret_stars() {
    local prompt="$1"
    local var_name="$2"
    local input=""
    local char=""

    printf "%s" "$prompt"

    while IFS= read -r -s -n1 char; do
        case "$char" in
            $'\0'|$'\n'|$'\r')
                break
                ;;
            $'\177'|$'\b')
                if [ -n "$input" ]; then
                    input="${input%?}"
                    printf '\b \b'
                fi
                ;;
            *)
                input="${input}${char}"
                printf '*'
                ;;
        esac
    done

    printf '\n'
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
