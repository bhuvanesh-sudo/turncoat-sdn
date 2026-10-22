<!--
One pull request per release: release-v0.x into main, opened by jv as a draft
at kickoff so CI runs on every push. Mark Ready for review after the
show-and-tell.
Title format: release: v0.x <release goal>   e.g. release: v0.1 the simulator runs on its own
-->

## Release goal

<!-- The goal and demo from the release plan, and whether the show-and-tell passed. -->

## Tasks in this release

<!-- One line per task issue. Tick it when its rota reviewer has reviewed the commits. -->

- [ ] #  bv:
- [ ] #  arj:
- [ ] #  ash:
- [ ] #  arv:
- [ ] #  jv:

## How it was tested

<!-- Commands run on a clean install, and what they showed. For ported code, say how the numbers were checked against the final-year project. -->

```
pytest
ruff check .
ruff format --check .
```

## Definition of done

- [ ] Every task's **Done when** condition is met
- [ ] Every task's commits reviewed by its rota reviewer
- [ ] Tests added or updated, and CI green
- [ ] Each task's doc page written or updated
- [ ] One line per task in `CHANGELOG.md` under "Unreleased"
- [ ] Any new command or option shown in `docs/cli.md`
- [ ] No core module imports `os_ken`, `ryu` or `mininet`

## Approval

<!-- Needs green CI and an approval from a member other than the author. Merge with Rebase and merge or Create a merge commit, never Squash. -->

@
