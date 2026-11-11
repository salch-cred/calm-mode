"""calm-mode: when you get frustrated, your agent slows down.

Calm Mode reads the tone of each of your messages: "still broken", "I already told you", all caps,
"!!!", the same message twice. Frustration builds over a few messages and fades when you're happy.
When it crosses the line, the agent switches to careful mode until things settle:

- it is told to take one step at a time, say what it will do first, and check each change;
- in code: at most `max_edits` file edits per turn, and risky commands (rm -rf, git push,
  deploys, DROP TABLE...) wait until you say "yes, go ahead".

  /calm          the current level, what it noticed, and the mode
  /calm on|off   force careful mode on or off for this session
  /calm auto     back to reading your tone
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from . import signals as S

if TYPE_CHECKING:
    from hermes_cli.plugins import PluginContext

_CTX: Any = None
_LOCK = threading.Lock()


@dataclass
class Session:
    level: float = 0.0
    careful: bool = False
    forced: Optional[bool] = None        # /calm on|off
    last: str = ""
    signs: list[str] = field(default_factory=list)
    turn: str = ""
    edits: int = 0
    approved: bool = False
    blocked: int = 0
    switched_on: int = 0

    @property
    def active(self) -> bool:
        return self.forced if self.forced is not None else self.careful


_SESSIONS: dict[str, Session] = {}
EDIT_TOOLS = {"write_file", "patch"}

CAREFUL = """[Calm Mode] The user is frustrated ({why}). For the rest of this turn, work carefully:
- Start with one short sentence that states what you'll do now. No long apologies.
- Make one change at a time, then check it (run it, its tests, or read the result) before the next.
- Don't say anything is fixed until you've checked it; if you couldn't check, say so.
- If you're unsure what they want, ask one short question instead of guessing.
- Risky commands (deleting files, git push, deploys, database changes) are held until the user says yes.
- At most {max_edits} file edits this turn."""


def _setting(name: str, default: Any) -> Any:
    try:
        value = _CTX.get_config(name, default) if _CTX is not None else default
    except Exception:
        value = default
    return default if value is None or value == "" else value


def _num(name: str, default: float) -> float:
    try:
        return float(_setting(name, default))
    except (TypeError, ValueError):
        return default


def _text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return " ".join(p.get("text", "") for p in message if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _session(sid: str) -> Session:
    s = _SESSIONS.get(sid)
    if s is None:
        s = _SESSIONS[sid] = Session()
        while len(_SESSIONS) > 500:
            _SESSIONS.pop(next(iter(_SESSIONS)))
    return s


# hooks ------------------------------------------------------------------

def on_pre_llm_call(session_id: str = "", turn_id: str = "", user_message: Any = None, **_: Any) -> Optional[dict]:
    text = _text(user_message).strip()
    if not text or text.startswith("/"):
        return None
    on_at, off_at = _num("threshold", 3), _num("calm_below", 1)
    with _LOCK:
        s = _session(session_id or "")
        reading = S.read(text, s.last)
        s.level = S.level_after(s.level, reading)
        s.last, s.turn, s.edits = text, turn_id or "", 0
        s.approved = bool(S.APPROVE.search(text))
        if reading.signs:
            s.signs = (s.signs + reading.signs)[-6:]
        if not s.careful and s.level >= on_at:
            s.careful = True
            s.switched_on += 1
        elif s.careful and s.level < off_at:
            s.careful = False
        if not s.active:
            return None
        why = ", ".join(dict.fromkeys(s.signs[-3:])) or "you turned careful mode on"
        return {"context": CAREFUL.format(why=why, max_edits=int(_num("max_edits", 2)))}


def on_pre_tool_call(tool_name: str = "", args: Any = None, session_id: str = "", **_: Any) -> Optional[dict]:
    with _LOCK:
        s = _SESSIONS.get(session_id or "")
        if s is None or not s.active:
            return None
        if tool_name == "terminal" and isinstance(args, dict):
            command = str(args.get("command") or "")
            if S.risky(command) and not s.approved:
                s.blocked += 1
                return {"action": "block", "message": (
                    f"Calm Mode: the user is frustrated, so risky commands wait for their OK. Don't run "
                    f"`{command[:120]}` yet: tell them in one sentence what it will do and ask "
                    f"\"Shall I run it?\". It runs once they say yes.")}
        if tool_name in EDIT_TOOLS:
            limit = int(_num("max_edits", 2))
            if s.edits >= limit:
                s.blocked += 1
                return {"action": "block", "message": (
                    f"Calm Mode: {limit} file edits is the limit for this turn while the user is frustrated. "
                    "Stop here, check what you changed (run it or its tests), and tell them the result "
                    "before changing more.")}
            s.edits += 1
    return None


# command ----------------------------------------------------------------

def _bar(level: float, on_at: float) -> str:
    filled = min(10, round(level / max(on_at, 0.1) * 5))
    return "▮" * filled + "▯" * (10 - filled)


def calm_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    action = (raw_args or "").strip().lower()
    with _LOCK:
        s = _session(session_id or "")
        if action in ("on", "off"):
            s.forced = action == "on"
            return f"Careful mode is {'on' if s.forced else 'off'} for this session until /calm auto."
        if action == "auto":
            s.forced = None
            return "Calm Mode is reading your tone again."
        if action not in ("", "status"):
            return "Usage: /calm [on | off | auto]"
        on_at = _num("threshold", 3)
        mode = ("careful (forced)" if s.forced else "normal (forced)") if s.forced is not None else (
            "careful" if s.careful else "normal")
        lines = [f"Calm Mode: {mode}.",
                 f"Frustration {_bar(s.level, on_at)} {s.level:.1f} (careful mode from {on_at:g})."]
        if s.signs:
            lines.append("Noticed: " + ", ".join(dict.fromkeys(s.signs)) + ".")
        lines.append(f"Careful mode switched on {s.switched_on} time(s); {s.blocked} action(s) held back.")
        return "\n".join(lines)


def register(ctx: "PluginContext") -> None:
    global _CTX
    _CTX = ctx
    with _LOCK:
        _SESSIONS.clear()
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_command("calm", calm_command, description="When you get frustrated, your agent slows down",
                         args_hint="[on|off|auto]")
