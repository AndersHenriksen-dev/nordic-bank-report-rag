"""PreToolUse hook: block editing Python code before the style guide has been read.

Wired up in .claude/settings.json for the Edit/Write/NotebookEdit tools. Before an agent may
write or edit a .py (or .ipynb, since notebook cells are Python too) file in this session, it
must have used the Read tool on .claude/reference/python-style.md at least once. This keeps the
project's typing/docstring/structure rules ("KISS, DRY, LEAN, reads like a book of chapters";
see that file) in front of every agent that writes Python here, instead of relying on them to
remember to check it.

Claude Code invokes this script with the hook's JSON payload on stdin and reads its decision
from stdout; see https://code.claude.com/docs/en/hooks-guide.md for the general contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

STYLE_GUIDE_PATH = (Path(__file__).resolve().parent.parent / "reference" / "python-style.md").resolve()

# Tools this hook cares about, and where each keeps the path of the file being written.
FILE_PATH_KEYS: dict[str, str] = {
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}

PYTHON_EXTENSIONS = (".py", ".pyi", ".ipynb")


def allow() -> None:
    """Let the tool call through with no comment: the default, unblocked outcome."""
    sys.exit(0)


def deny(reason: str) -> None:
    """Block the tool call and hand the agent an actionable reason to act on."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            },
        ),
    )
    sys.exit(0)


def resolve_against(raw_path: str, cwd: str) -> Path:
    """Resolve a possibly-relative path from the hook payload to an absolute path.

    Args:
        raw_path: The path as it appears in tool_input or a transcript entry.
        cwd: The working directory reported alongside that path, used to resolve relative paths.

    Returns:
        An absolute, OS-normalized path suitable for equality comparison.
    """
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    return candidate.resolve()


def style_guide_was_read(transcript_path: str, cwd: str) -> bool:
    """Scan the session transcript for a prior Read of the style guide.

    Args:
        transcript_path: Path to the session's JSONL transcript, as given by the hook payload.
        cwd: The session's working directory, for resolving relative paths found in the transcript.

    Returns:
        True if a completed Read tool call against the style guide appears anywhere in the
        transcript so far; False if the transcript is missing, unreadable, or contains no such call.
    """
    path = Path(transcript_path)
    if not path.is_file():
        return False

    with path.open("r", encoding="utf-8-sig", errors="ignore") as transcript:
        for line in transcript:
            line = line.strip()
            if not line or '"Read"' not in line:
                continue  # cheap pre-filter before paying for json.loads on every line
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # transcript is written asynchronously; a trailing line may be partial

            for item in entry.get("message", {}).get("content", []) or []:
                if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") != "Read":
                    continue
                raw_path = item.get("input", {}).get("file_path")
                if not raw_path:
                    continue
                if resolve_against(raw_path, cwd) == STYLE_GUIDE_PATH:
                    return True

    return False


def main() -> None:
    """Read the hook payload from stdin and allow or deny the pending tool call."""
    try:
        # utf-8-sig strips a leading BOM if present - PowerShell pipes stdin with one by default.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        allow()  # malformed payload is a hook-plumbing problem, not something to block work over
        return

    tool_name = payload.get("tool_name", "")
    file_path_key = FILE_PATH_KEYS.get(tool_name)
    if file_path_key is None:
        allow()
        return

    target_path = payload.get("tool_input", {}).get(file_path_key, "")
    if not target_path.lower().endswith(PYTHON_EXTENSIONS):
        allow()
        return

    cwd = payload.get("cwd", ".")
    if resolve_against(target_path, cwd) == STYLE_GUIDE_PATH:
        allow()  # editing the style guide itself is not "writing Python code"
        return

    transcript_path = payload.get("transcript_path", "")
    try:
        already_read = style_guide_was_read(transcript_path, cwd)
    except OSError:
        allow()  # fail open on unexpected I/O errors rather than blocking all Python work
        return

    if already_read:
        allow()
    else:
        deny(
            "Read .claude/reference/python-style.md before editing Python files in this repo - "
            "it covers typing, docstrings, structure, and testing conventions that apply to every "
            f".py/.ipynb change. Read it once, then retry editing {target_path}.",
        )


if __name__ == "__main__":
    main()
