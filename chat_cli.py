#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

try:
    import readline  # noqa: F401
except ImportError:
    readline = None  # type: ignore

from openai import OpenAI

APP_NAME = "synth-chat"
HOME = Path.home()
HISTORY_FILE = HOME / f".{APP_NAME}_history"
SESSION_FILE = HOME / f".{APP_NAME}_session.json"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

DEFAULT_SYSTEM_PROMPT = """You are a precise senior coding assistant.
Focus on practical answers, debugging, Linux, SQL, Python, architecture, and clean code.
Rules:
- prefer copy-paste-friendly output
- avoid deprecated patterns
- keep code runnable
- UTC internally, convert only at display/UI time when needed
- be concise unless asked otherwise
"""

HELP_TEXT = """
Commands
--------
/help                  Show help
/model                 Show current model
/model <name>          Set model
/system                Show current system prompt
/system reset          Reset system prompt
/system set <text>     Replace system prompt
/clear                 Clear conversation memory
/history               Show message count
/save                  Save session
/load                  Load session
/multi                 Multiline mode, end with a line containing only END
/last                  Show last assistant answer
/copylast <file>       Save last assistant answer to file
/paste <file>          Send file contents as next user message
/sql                   Switch to SQL-oriented system prompt
/python                Switch to Python-oriented system prompt
/debug                 Switch to debugging-oriented system prompt
/compact               Keep only system + last 8 messages
/exit                  Save and quit
"""

SQL_PROMPT = """You are a senior SQL assistant.
Target MariaDB by default unless the user says otherwise.
Return copy-paste-ready SQL.
Prefer clear aliases, safe filters, and explain assumptions briefly.
"""

PYTHON_PROMPT = """You are a senior Python assistant.
Write modern, runnable Python.
Avoid deprecated patterns.
Prefer clean structure, type hints where useful, and small focused comments.
"""

DEBUG_PROMPT = """You are a debugging assistant.
Be systematic:
1. likely cause
2. checks to run
3. minimal fix
4. improved fix
Keep answers practical and direct.
"""


def load_history() -> None:
    if readline and HISTORY_FILE.exists():
        try:
            readline.read_history_file(str(HISTORY_FILE))
        except Exception:
            pass


def save_history() -> None:
    if readline:
        try:
            readline.write_history_file(str(HISTORY_FILE))
        except Exception:
            pass


def save_session(state: dict[str, Any]) -> None:
    payload = {
        "model": state["model"],
        "system_prompt": state["system_prompt"],
        "messages": state["messages"],
        "last_answer": state.get("last_answer", ""),
    }
    SESSION_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_session() -> dict[str, Any]:
    if not SESSION_FILE.exists():
        raise FileNotFoundError(f"No saved session at {SESSION_FILE}")
    data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    return {
        "model": data.get("model", DEFAULT_MODEL),
        "system_prompt": data.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
        "messages": data.get("messages", []),
        "last_answer": data.get("last_answer", ""),
    }


def compact_messages(messages: list[dict[str, str]], keep_last: int = 8) -> list[dict[str, str]]:
    if len(messages) <= keep_last:
        return messages[:]
    return messages[-keep_last:]


def multiline_input() -> str:
    print("Multiline mode. Finish with a line containing only END")
    lines: list[str] = []
    while True:
        try:
            line = input("... ")
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def build_input(messages: list[dict[str, str]], user_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for msg in messages:
        items.append({
            "role": msg["role"],
            "content": [{"type": "input_text", "text": msg["content"]}],
        })
    items.append({
        "role": "user",
        "content": [{"type": "input_text", "text": user_text}],
    })
    return items


def stream_response(
    client: OpenAI,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    user_text: str,
) -> str:
    final_text_parts: list[str] = []

    with client.responses.stream(
        model=model,
        instructions=system_prompt,
        input=build_input(messages, user_text),
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    print(delta, end="", flush=True)
                    final_text_parts.append(delta)

            elif event_type == "response.error":
                err = getattr(event, "error", None)
                raise RuntimeError(str(err) if err else "Unknown streaming error")

        stream.get_final_response()

    print()
    return "".join(final_text_parts).strip()


def read_file_text(path_str: str) -> str:
    path = Path(path_str).expanduser()
    return path.read_text(encoding="utf-8")


def write_file_text(path_str: str, text: str) -> Path:
    path = Path(path_str).expanduser()
    path.write_text(text, encoding="utf-8")
    return path


def print_banner(state: dict[str, Any]) -> None:
    print(f"{APP_NAME} | model={state['model']}")
    print("Type /help for commands.\n")


def handle_command(raw: str, state: dict[str, Any]) -> tuple[bool, str | None]:
    if not raw.startswith("/"):
        return False, None

    parts = shlex.split(raw)
    cmd = parts[0].lower()

    if cmd == "/help":
        print(HELP_TEXT)
        return True, None

    if cmd == "/exit":
        save_session(state)
        save_history()
        raise SystemExit(0)

    if cmd == "/model":
        if len(parts) == 1:
            print(state["model"])
        else:
            state["model"] = parts[1]
            print(f"model = {state['model']}")
        return True, None

    if cmd == "/system":
        if len(parts) == 1:
            print(state["system_prompt"])
            return True, None
        if len(parts) >= 2 and parts[1] == "reset":
            state["system_prompt"] = DEFAULT_SYSTEM_PROMPT
            print("system prompt reset")
            return True, None
        if len(parts) >= 3 and parts[1] == "set":
            state["system_prompt"] = raw.split("/system set", 1)[1].strip()
            print("system prompt updated")
            return True, None
        print("use /system, /system reset, or /system set <text>")
        return True, None

    if cmd == "/sql":
        state["system_prompt"] = SQL_PROMPT
        print("switched to SQL prompt")
        return True, None

    if cmd == "/python":
        state["system_prompt"] = PYTHON_PROMPT
        print("switched to Python prompt")
        return True, None

    if cmd == "/debug":
        state["system_prompt"] = DEBUG_PROMPT
        print("switched to Debug prompt")
        return True, None

    if cmd == "/clear":
        state["messages"] = []
        state["last_answer"] = ""
        print("conversation cleared")
        return True, None

    if cmd == "/history":
        print(f"messages: {len(state['messages'])}")
        return True, None

    if cmd == "/save":
        save_session(state)
        print(f"saved: {SESSION_FILE}")
        return True, None

    if cmd == "/load":
        loaded = load_session()
        state.update(loaded)
        print(f"loaded: {SESSION_FILE}")
        return True, None

    if cmd == "/multi":
        text = multiline_input()
        return True, text if text else None

    if cmd == "/last":
        print(state.get("last_answer", ""))
        return True, None

    if cmd == "/copylast":
        if len(parts) < 2:
            print("usage: /copylast <file>")
            return True, None
        path = write_file_text(parts[1], state.get("last_answer", ""))
        print(f"written: {path}")
        return True, None

    if cmd == "/paste":
        if len(parts) < 2:
            print("usage: /paste <file>")
            return True, None
        text = read_file_text(parts[1])
        return True, text

    if cmd == "/compact":
        state["messages"] = compact_messages(state["messages"], keep_last=8)
        print(f"compacted to {len(state['messages'])} messages")
        return True, None

    print("unknown command")
    return True, None


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 1

    load_history()
    client = OpenAI()

    state: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "messages": [],
        "last_answer": "",
    }

    print_banner(state)

    while True:
        try:
            raw = input(">> ").strip()
            if not raw:
                continue

            handled, injected_text = handle_command(raw, state)
            if handled and injected_text is None:
                continue

            user_text = injected_text if injected_text is not None else raw

            # ---- autosummary check ----

            if len(state["messages"]) > MAX_MESSAGES:

                summary = summarize_messages(
                    client,
                    state["model"],
                    state["messages"][:-KEEP_LAST]
                )

                state["messages"] = [
                    {"role": "system", "content": f"Conversation summary:\n{summary}"}
                ] + state["messages"][-KEEP_LAST:]

                print("[conversation summarized]\n")

            print("\n--- assistant ---\n")
            answer = stream_response(
                client=client,
                model=state["model"],
                system_prompt=state["system_prompt"],
                messages=state["messages"],
                user_text=user_text,
            )
            print("\n-----------------\n")

            state["messages"].append({"role": "user", "content": user_text})
            state["messages"].append({"role": "assistant", "content": answer})
            state["last_answer"] = answer

            state["messages"].insert(0, {
                "role": "system",
                "content": state["system_prompt"]
            })

        except KeyboardInterrupt:
            print("\nInterrupted. Use /exit to quit.\n")
        except EOFError:
            print("\nSaving session and exiting.")
            save_session(state)
            save_history()
            return 0
        except Exception as exc:
            print(f"\n[ERROR] {type(exc).__name__}: {exc}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
