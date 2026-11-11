"""Reading frustration in what the user writes, and spotting risky commands. Plain text rules, no model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_REPEAT = re.compile(r"\b(?:still|again|same (?:error|issue|problem|bug|thing|result)|once more|yet again)\b", re.I)
_FAILED = re.compile(r"\b(?:doesn'?t|does not|didn'?t|did not|isn'?t|is not|won'?t)\s+(?:\w+\s+)?(?:work|fix|help|change|load|run)\w*\b|\bnot (?:working|fixed)\b|\b(?:broken|broke|wrong|worse)\b", re.I)
_TOLD = re.compile(r"\b(?:i (?:already )?(?:told|said|asked)(?: you)?|how many times|i just said|read what i|listen)\b", re.I)
_SWEAR = re.compile(r"\b(?:wtf|ffs|omg|damn|dammit|shit|fuck\w*|crap|ugh+|argh+|seriously|ridiculous|useless|stupid)\b", re.I)
_STOP = re.compile(r"^\s*(?:no+|nope|stop|wrong)\b[\s.!]*", re.I)
_CALM = re.compile(r"\b(?:thanks|thank you|perfect|great|works( now)?|nice|awesome|that did it|all good|lgtm)\b|👍|✅|🙏", re.I)
APPROVE = re.compile(r"\b(?:yes|yep|go ahead|do it|run it|approved?|proceed|ok(?:ay)?,? (?:do|run|go)|you can)\b", re.I)


@dataclass
class Reading:
    score: float
    signs: list[str] = field(default_factory=list)


def read(text: str, previous: str = "") -> Reading:
    """How frustrated one message sounds: about 0 for calm, 2-3 for clearly annoyed, 5+ for angry."""
    text = (text or "").strip()
    r = Reading(0.0)
    if not text:
        return r

    def add(points: float, sign: str):
        r.score += points
        r.signs.append(sign)

    if _REPEAT.search(text):
        add(1, "it's happening again")
    if _FAILED.search(text):
        add(1, "says it doesn't work")
    if _TOLD.search(text):
        add(2, "had to repeat themselves")
    if _SWEAR.search(text):
        add(2, "strong words")
    if _STOP.match(text):
        add(1, "a flat no")
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        add(2, "writing in capitals")
    if re.search(r"[!?]{2,}", text):
        add(1, "!!/??")
    if previous and text.lower() == previous.strip().lower():
        add(2, "sent the same message twice")
    if _CALM.search(text) and r.score < 2:
        r.score = -1.0
        r.signs = ["sounds happy"]
    return r


def level_after(level: float, reading: Reading, decay: float = 0.5) -> float:
    """Frustration builds over messages and fades when they're calm."""
    return max(0.0, level * decay + reading.score)


# risky commands ------------------------------------------------------------

RISKY = re.compile(r"""
    \brm\s+-[a-z]*[rf][a-z]*\b | \bRemove-Item\b.*-Recurse | \brmdir\s+/s\b | \bdel\s+/[sq]\b
  | \bgit\s+(?:push|reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s|rebase|branch\s+-D|stash\s+drop)\b
  | \b(?:npm|yarn|pnpm|cargo|twine|gem)\s+publish\b | \bdocker\s+(?:rm|rmi|system\s+prune|volume\s+rm)\b
  | \bkubectl\s+(?:delete|apply)\b | \bterraform\s+(?:apply|destroy)\b
  | \b(?:vercel|netlify|fly|heroku|firebase|wrangler)\b.*\b(?:deploy|--prod)\b
  | \bdrop\s+(?:table|database)\b | \btruncate\s+table\b | \bdelete\s+from\b
  | \b(?:shutdown|reboot|mkfs|dd\s+if=)\b | \bchmod\s+-R\b | \bchown\s+-R\b
""", re.I | re.X)


def risky(command: str) -> bool:
    return bool(command) and bool(RISKY.search(command))
