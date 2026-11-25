# Working in this repo

## Before you start

1. Pull `main`.
2. Make a branch: `git checkout -b feature/<area>-<short-name>`.
3. Work only in your area unless you have told the others you are touching something else.

Areas are listed in the table in [README.md](README.md). They line up with the division of
work in the Review 1 report, so your branch name should make it obvious who is writing it.

## The rule that is not negotiable

No raw identifier leaves the backend. Concretely:

- API responses carry `entity_id`, `category`, `risk`, `span` — never `value`.
- Log statements reference `entity_id`, never the text that was matched.
- Nothing from `data/` or `protected_store/` gets committed. `.gitignore` covers both,
  but check `git status` before you commit anyway.

If you need to see a raw value while debugging, read it locally. Do not put it in a
commit, a screenshot for the slides, or an issue comment.

## Schemas are shared

`backend/app/schemas/` holds the contracts between stages. Nandha's detection output is
Patan's orchestrator input; the risk agent's output is what the redaction agent executes.
Changing a field there breaks somebody else's work in progress.

So: raise it in the group before you change a schema, and put the change in its own small
pull request rather than burying it inside a feature branch.

## Pull requests

- One review from somebody other than you, then merge.
- Say in the description what you changed and what you did *not* get to.
- Don't merge something that breaks `pytest backend/tests`.

## Commits

Short and plain. `add presidio recognizer for aadhaar numbers` is fine.
`fix stuff` is not.
