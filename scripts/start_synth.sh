#!/usr/bin/env bash

PROJECT_ROOT="$HOME/projects/synth-v2"
cd "$PROJECT_ROOT" || return 1

source venv/bin/activate

unalias catt 2>/dev/null || true

catt() {
    if command -v clip.exe >/dev/null 2>&1; then
        if [ $# -eq 0 ]; then
            clip.exe
        else
            cat "$@" | clip.exe
        fi
        echo "[OK] copied to Windows clipboard"
    else
        echo "[WARN] clip.exe not found"
        if [ $# -eq 0 ]; then
            cat
        else
            cat "$@"
        fi
    fi
}

echo "[OK] synth venv active"
echo "[OK] catt function ready"
type catt
