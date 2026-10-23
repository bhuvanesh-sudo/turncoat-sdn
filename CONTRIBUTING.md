# Contributing to turncoat-sdn

Thanks for helping. This page explains how to propose a change, from setting
up your machine to getting a pull request merged.

## 1. Set up a development environment

You need Python 3.11 or newer and Git. You do **not** need os-ken, Mininet or
root access for anything in the core package.

```bash
git clone https://github.com/bhuvanesh-sudo/turncoat-sdn.git
cd turncoat-sdn
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Check that everything works:

```bash
pytest                 # run the test suite
ruff check .           # lint
ruff format --check .  # formatting
```

CI runs exactly these three commands, so if they pass locally your push
should pass too.

## 2. Pick up a task

- Every task is a GitHub Issue on the project board, labelled with its release
  milestone (`v0.1`, `v0.2`, ...). Open one with the **Release task** template
  if it does not exist yet.
- Assign yourself before you start, and check the issue's **Starts after**
  field. Don't start a task whose dependency hasn't landed on the release
  branch yet.

## 3. Branches

There is one branch per release, and everyone works on it directly:

```
release-v0.1
release-v0.2
release-v0.3
```

At each kickoff, jv creates the release branch from an up-to-date `main` and
opens a **draft** pull request from it into `main`, so CI runs on every push.
There are no per-task branches.

Never commit to `main` directly. `main` is protected: changes reach it only
through the release pull request, reviewed and with green CI.

Because five people push to the same branch, follow these rules every time:

- **Pull before you start and before you push:**
  `git pull --rebase origin release-v0.x`.
- **Run the checks before you push:** `pytest`, `ruff check .` and
  `ruff format --check .`. Never push a red branch, because it blocks everyone.
- **Never force-push** the release branch, and never rewrite commits that are
  already pushed.
- **Expect conflicts in shared files** (`CHANGELOG.md`, `tests/README.md`,
  `docs/README.md`). Keep your edits to them small, and resolve conflicts by
  keeping both sides.

## 4. Commits

Commit little and often, in the
[Conventional Commits](https://www.conventionalcommits.org/) style:

```
<type>(<scope>): <summary in the imperative, lower case, no full stop>
```

| Type | Use it for |
|---|---|
| `feat` | New behaviour (`feat(scoring): add detection latency`) |
| `fix` | A bug fix (`fix(sim): pair arrival streams by seed`) |
| `test` | Tests only (`test(sim): golden file for seed 1`) |
| `docs` | Documentation only (`docs(attacks): describe grayhole`) |
| `refactor` | Restructuring with no behaviour change |
| `chore` / `ci` / `build` | Tooling, CI and packaging |

Scopes match the package folders: `sim`, `attacks`, `strategies`, `trust`,
`events`, `scoring`, `stats`, `cli`, plus `repo`, `ci` and `docs`.

Aim for several small commits per task rather than one large one. A reviewer
should be able to read the history and follow how the change was built.

## 5. Reviews and merging

1. When your task is done, push it to the release branch and ask your reviewer
   from the rota below to review your commits. They comment on the commits on
   GitHub, and you fix anything they raise in new commits.
2. Mention the task's issue in your commit messages (`Refs #12`) so the
   reviewer can find every commit that belongs to it.
3. At the end of the release, jv marks the release pull request **Ready for
   review**. It needs green CI and an approval from another member before it
   merges.
4. Merge the release pull request with *Rebase and merge* or *Create a merge
   commit*, never *Squash and merge*, so every contributor's history survives
   on `main`.

### Review rota

| Author | Reviewer |
|---|---|
| bv | arj |
| arj | ash |
| ash | arv |
| arv | jv |
| jv | bv |

### What reviewers check

- The task's **Done when** condition from the issue is actually met.
- New behaviour has tests, and CI is green.
- No core module imports `os_ken`, `ryu` or `mininet`. Ruff and
  `tests/test_package.py` both enforce this.
- Numbers ported from the final-year project still match. If a golden-file
  test fails, fix the move, never the expected numbers.
- Anything that writes or reads `events.jsonl` agrees with
  `docs/event-format.md`, and recordings it produces pass the validator.

## 6. Definition of done

A task is done only when all of these are true:

- [ ] Commits pushed to the release branch and reviewed by your rota reviewer
- [ ] Tests added or updated, and CI green on the release pull request
- [ ] The doc page for the task written or updated in the same push
- [ ] One line added to `CHANGELOG.md` under "Unreleased"
- [ ] Any new command or option shown in `docs/cli.md`

## 7. Code rules

- **Core stays SDN-free.** Code that needs os-ken or Mininet goes under
  `backends/`, never under `src/turncoat_sdn/`.
- **Seeds are sacred.** Anything random takes an explicit seed, a seeded
  `random.Random` or a `numpy.random.Generator`. Never use the global random
  state.
- **`sim` stays on its own.** The simulator imports nothing else from
  `turncoat_sdn`. Routing, trust, the latency tell and the recorder are hooks
  the caller passes in (see `docs/architecture.md`).
- **Runs are recorded in the shared format.** Anything that produces runs
  writes them with `turncoat_sdn.events.EventWriter`, and its tests check that
  the result passes `turncoat_sdn.events.validate`. A change to the schema
  itself goes through arj, updates `docs/event-format.md` in the same push, and
  bumps `SCHEMA_VERSION` when a reader would notice.
- **Port, then improve.** When moving code from the final-year project, first
  move it unchanged and prove the numbers match, then refactor in a separate
  commit.
- **Leave internal notes behind.** Strip references to `plan.md`,
  `panel_fix.md`, `memory/` notes and run-specific comments when porting.
- **No generated artefacts in Git.** That means PDFs, results CSVs, figures,
  recordings and archives. Regenerate them from code. Small hand-written
  fixtures under `tests/`, such as `tests/events/sample_run.jsonl`, are the
  exception; tests that need a full run record one into `tmp_path`.

## 8. Rhythm

- **Kickoff** at the start of each release (30 minutes): confirm tasks,
  dependencies and open questions.
- **Weekly check-in** (15 minutes): what landed, what's next, what's blocking.
- **Show-and-tell** at the end of each release: one person demos the release
  end to end from a clean install, then jv tags it.

## 9. Releases

jv merges the release pull request and tags `main` once the show-and-tell
passes:

```bash
git tag -a v0.1.0 -m "v0.1: the simulator runs on its own"
git push origin v0.1.0
```

Before tagging, move the "Unreleased" entries in `CHANGELOG.md` under the new
version heading and bump `version` in `pyproject.toml`.
