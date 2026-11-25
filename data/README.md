# data/

**Nothing in here is committed.** `.gitignore` excludes the whole directory apart from
this file and the `.gitkeep` placeholders.

| Folder | What goes in it |
|---|---|
| `annotated/` | Documents that arrive with personal-information annotations |
| `synthetic/` | The synthetic corpus we generate ourselves |
| `samples/` | Small inputs for manual testing |

## Use synthetic data

We are not putting real personal information through this system during development.
Apart from the obvious reason, synthetic data is the only way we know the ground truth
exactly - and without ground truth we cannot tell whether the verification agent is
catching anything or just agreeing with the first pass.

The synthetic set needs to contain, deliberately:

- direct identifiers in several formats (Indian and international)
- indirect identification: role + place + date that names nobody and identifies one person
- the same person across several documents, for linkage testing
- near-misses that should *not* be redacted - invoice numbers, public office names

Owner: shared, coordinated by Nandha Jyothi E
