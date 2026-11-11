"""Calm Mode as Hermes drives it."""

import pytest
import calm_mode
from calm_mode import signals as S


class FakeCtx:
    def __init__(self, settings=None):
        self.settings, self.hooks, self.commands = settings or {}, {}, {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, cb, **_):
        self.hooks.setdefault(name, []).append(cb)

    def register_command(self, name, handler, **_):
        self.commands[name] = handler

    def fire(self, name, **kw):
        return [cb(**kw) for cb in self.hooks.get(name, [])]


@pytest.fixture
def ctx():
    fake = FakeCtx()
    calm_mode.register(fake)
    return fake


def say(ctx, text, turn="T", session="S1"):
    return ctx.fire("pre_llm_call", session_id=session, turn_id=turn, user_message=text)[0]


def tool(ctx, name, session="S1", **args):
    return ctx.fire("pre_tool_call", tool_name=name, args=args, session_id=session)[0]


# reading tone -------------------------------------------------------------

@pytest.mark.parametrize("text,low,high", [
    ("can you add a dark mode toggle?", 0, 0),
    ("thanks, that works!", -1, -1),
    ("it's still broken", 2, 2),
    ("I ALREADY TOLD YOU THE BUTTON IS WRONG!!!", 6, 8),
    ("wtf, same error again", 3, 3),
    ("nope", 1, 1),
])
def test_reading(text, low, high):
    assert low <= S.read(text).score <= high


def test_same_message_twice():
    assert "sent the same message twice" in S.read("fix the login", "Fix the login").signs


def test_level_builds_and_fades():
    level = 0.0
    for text in ("still broken", "still not working", "it's still wrong"):
        level = S.level_after(level, S.read(text))
    assert level >= 3
    for text in ("ok", "thanks, works now"):
        level = S.level_after(level, S.read(text))
    assert level < 1


@pytest.mark.parametrize("command,is_risky", [
    ("rm -rf build", True), ("git push origin main", True), ("git reset --hard HEAD~1", True),
    ("npm publish", True), ("vercel deploy --prod", True), ("psql -c 'DROP TABLE users'", True),
    ("terraform apply", True), ("kubectl delete pod x", True),
    ("pytest -q", False), ("git status", False), ("ls -la", False), ("rm notes.txt", False),
])
def test_risky(command, is_risky):
    assert S.risky(command) is is_risky


# the flow ---------------------------------------------------------------

def test_calm_user_gets_nothing(ctx):
    assert say(ctx, "add a dark mode toggle") is None
    assert tool(ctx, "terminal", command="git push") is None


def test_frustration_switches_careful_mode_on(ctx):
    assert say(ctx, "it's still broken", "T1") is None
    out = say(ctx, "I ALREADY TOLD YOU, it's the same error!!", "T2")
    assert out and "[Calm Mode] The user is frustrated" in out["context"]
    assert "had to repeat themselves" in out["context"] and "At most 2 file edits" in out["context"]


def test_careful_mode_holds_risky_commands_until_yes(ctx):
    say(ctx, "WTF, STILL BROKEN!!", "T1")
    block = tool(ctx, "terminal", command="git push origin main")
    assert block["action"] == "block" and "Shall I run it?" in block["message"]
    assert tool(ctx, "terminal", command="pytest -q") is None
    say(ctx, "yes, go ahead and push", "T2")
    assert tool(ctx, "terminal", command="git push origin main") is None


def test_careful_mode_limits_edits_per_turn(ctx):
    say(ctx, "WTF, STILL BROKEN!!", "T1")
    assert tool(ctx, "patch", path="a.py") is None
    assert tool(ctx, "write_file", path="b.py") is None
    third = tool(ctx, "patch", path="c.py")
    assert third["action"] == "block" and "check what you changed" in third["message"]
    say(ctx, "still wrong", "T2")
    assert tool(ctx, "patch", path="c.py") is None                 # a new turn, a new allowance


def test_switches_off_when_the_user_is_happy(ctx):
    say(ctx, "WTF, STILL BROKEN!!", "T1")
    say(ctx, "ok", "T2")
    say(ctx, "thanks, that works", "T3")
    assert say(ctx, "now add a footer", "T4") is None
    assert tool(ctx, "terminal", command="git push") is None


def test_sessions_are_separate(ctx):
    say(ctx, "WTF, STILL BROKEN!!", session="A")
    assert tool(ctx, "terminal", session="B", command="git push") is None


def test_command_on_off_auto_and_status(ctx):
    cmd = ctx.commands["calm"]
    assert "on for this session" in cmd("on", session_id="S1")
    assert "Calm Mode] The user is frustrated (you turned careful mode on)" in say(ctx, "add a footer")["context"]
    assert cmd("off", session_id="S1").startswith("Careful mode is off")
    assert say(ctx, "WTF STILL BROKEN!!!") is None
    cmd("auto", session_id="S1")
    status = cmd("", session_id="S1")
    assert "Calm Mode: careful." in status and "Noticed:" in status and "strong words" in status
    assert "Usage" in cmd("loud", session_id="S1")


def test_slash_commands_are_not_read_as_tone(ctx):
    assert say(ctx, "/calm") is None
    assert ctx.commands["calm"]("", session_id="S1").startswith("Calm Mode: normal.")


def test_settings():
    fake = FakeCtx({"threshold": 1, "max_edits": 1})
    calm_mode.register(fake)
    assert "At most 1 file edits" in say(fake, "still broken")["context"]
    assert tool(fake, "patch", path="a") is None
    assert tool(fake, "patch", path="b")["action"] == "block"


def test_hooks_never_raise_on_junk(ctx):
    assert ctx.fire("pre_llm_call", user_message=None) == [None]
    assert ctx.fire("pre_tool_call", tool_name="terminal", args=None) == [None]
