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

CI runs exactly these three commands, so if they pass locally your pull
request should pass too.

## 2. Pick up a task

- Every task is a GitHub Issue on the project board, labelled with its release
  milestone (`v0.1`, `v0.2`, ...). Open one with the **Release task** template
  if it does not exist yet.
- Assign yourself before you start, and check the issue's **Starts after**
  field. Don't start a task whose dependency hasn't merged.

## 3. Branches

One branch per task, named `v0.x/<initials>-<short-task>`:

```
v0.1/jv-repo-scaffold
v0.2/arj-event-schema
v0.3/bv-grayhole-attack
```

Branch from an up-to-date `main`, and never commit to `main` directly. `main`
is protected: changes reach it only through a reviewed pull request with green
CI.

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

## 5. Pull requests

1. Open a **draft** pull request on the first day of the task, so teammates
   can see progress.
2. Fill in the template: what changed, how it was tested, which docs were
   updated.
3. When it's ready, mark it **Ready for review** and request your reviewer
   from the rota below.
4. The **reviewer** merges, not the author. Use *Squash and merge* only if the
   individual commits are noise; otherwise use *Rebase and merge* to keep the
   history.

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

## 6. Definition of done

A task is done only when all of these are true:

- [ ] Code merged to `main` through a reviewed pull request
- [ ] Tests added or updated, and CI green
- [ ] The doc page for the task written or updated in the same pull request
- [ ] One line added to `CHANGELOG.md` under "Unreleased"
- [ ] Any new command or option shown in `docs/cli.md`

## 7. Code rules

- **Core stays SDN-free.** Code that needs os-ken or Mininet goes under
  `backends/`, never under `src/turncoat_sdn/`.
- **Seeds are sacred.** Anything random takes an explicit seed or
  `numpy.random.Generator`. Never use the global random state.
- **Port, then improve.** When moving code from the final-year project, first
  move it unchanged and prove the numbers match, then refactor in a separate
  commit.
- **Leave internal notes behind.** Strip references to `plan.md`,
  `panel_fix.md`, `memory/` notes and run-specific comments when porting.
- **No generated artefacts in Git.** That means PDFs, results CSVs, figures,
  recordings and archives. Regenerate them from code.

## 8. Rhythm

- **Kickoff** at the start of each release (30 minutes): confirm tasks,
  dependencies and open questions.
- **Weekly check-in** (15 minutes): what merged, what's next, what's blocking.
- **Show-and-tell** at the end of each release: one person demos the release
  end to end from a clean install, then jv tags it.

## 9. Releases

jv tags each release from `main` once its show-and-tell passes:

```bash
git tag -a v0.1.0 -m "v0.1: the simulator runs on its own"
git push origin v0.1.0
```

Before tagging, move the "Unreleased" entries in `CHANGELOG.md` under the new
version heading and bump `version` in `pyproject.toml`.
