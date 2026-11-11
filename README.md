# calm-mode

**When you get frustrated, your agent slows down.**

You've seen it happen. The agent breaks something, you say "still broken", and it rushes into five more edits, a force push and a confident "Fixed!". By the third round you're typing in capitals.

A good colleague notices when you're annoyed and slows down. Calm Mode gives your agent that sense.

```text
you:   it's still broken
you:   WTF, I ALREADY TOLD YOU IT'S THE SAME ERROR!!

[Calm Mode] The user is frustrated (had to repeat themselves, strong words, writing in capitals).
  - Start with one short sentence that states what you'll do now.
  - Make one change at a time, then check it before the next.
  - Don't say anything is fixed until you've checked it.
  ...

agent tries: git push origin main
  -> held: "Calm Mode: the user is frustrated, so risky commands wait for their OK."
agent tries: a 3rd file edit this turn
  -> held: "Stop here, check what you changed, and tell them the result."
```

## How it works

**1. It reads your tone, without a model.** Each message gets a score from simple text rules:

| Sign | Points |
|---|---|
| "still", "again", "same error" | 1 |
| "doesn't work", "broken", "wrong" | 1 |
| "I already told you", "how many times" | 2 |
| Strong words ("wtf", "ffs", "useless"...) | 2 |
| Writing in capitals | 2 |
| "!!" or "??" | 1 |
| A flat "no" or "nope" | 1 |
| The same message sent twice | 2 |

A happy message ("thanks, works now") counts −1.

**2. Frustration builds and fades.** Your level is half of the previous level plus the new score. One grumpy message won't trigger it, but three in a row will. Careful mode starts at 3 and ends below 1.

**3. In careful mode, rules are enforced in code, not just suggested:**
- The agent is told, at the start of each turn, to work in small, checked steps and not to claim "fixed" without checking.
- **At most 2 file edits per turn.** Further edits are stopped with "check what you changed first".
- **Risky commands wait for your OK:** `rm -rf`, `git push`, `git reset --hard`, publishing packages, deploys (Vercel, Netlify, Fly…), `terraform apply`, `kubectl delete`, `DROP TABLE`, and similar. Say "yes, go ahead" and they run.

## Use it

```text
/calm          the level, what it noticed, and the mode
/calm on       careful mode for this session, whatever your tone
/calm off      never careful in this session
/calm auto     back to reading your tone
```

## Settings

```yaml
plugins:
  entries:
    calm-mode:
      settings:
        threshold: 3     # level at which careful mode starts
        calm_below: 1    # careful mode ends below this
        max_edits: 2     # file edits per turn in careful mode
```

## What it touches

- **Reads your messages** to score their tone, in memory, per session. Nothing is written to disk.
- **Adds context to your turn** (through `pre_llm_call`) only while careful mode is on.
- **Stops tool calls** (through `pre_tool_call`) only in careful mode: risky terminal commands until you say yes, and edits beyond the per-turn limit.
- **No model calls, no network, no files, no dependencies.**

## Limits

- **English tone rules.** Frustration in other languages is only caught through capitals, "!!" and repeated messages.
- **The risky-command list is a pattern list.** It catches common destructive commands, not every one.

## Development

```bash
pytest tests
```

30 tests cover tone scores, build-up and fading, the risky-command list, held commands and approval, the edit limit, sessions, and the commands.

## License

MIT
