# Documentation

Every page follows one template: **what it is**, **why it exists**, **how to
use it** (with a runnable example), **how it works inside**, and **known
limits**. The owner writes the page and keeps it accurate. Teammates add
sections for their own work, and the owner reviews those additions.

| Page | Owner | Written in | Question it answers |
|---|---|---|---|
| `simulator.md` | bv | v0.1, extended in v0.2 | How does a run work, and why are seeds paired? |
| `../INSTALL.md` | bv | v0.1, Mininet section in v1.0 | How do I install it, with or without the live testbed? |
| `../backends/mininet/README.md` | bv | v1.0 | How does the live testbed work, and what does it share with the simulator? |
| `results.md` | bv | v0.4 | What does a full comparison look like, and how do I reproduce it? |
| `event-format.md` | arj | v0.2, extended in v0.4 | What exactly is in a recording and a results file? |
| `architecture.md` | arj | v0.1 | How do the parts fit, and what depends on what? |
| `extending.md` | arj | v1.0 | How do I plug in my own attack, strategy or system? |
| `concepts.md` | ash | v0.1 | What are trust, EdgeScore, the gate and ground truth? |
| `trust-model.md` | ash | v0.1 | Why can the formula not catch a liar on its own? |
| `attacks.md` | ash | v0.3 | How does each turncoat behave, and how do I write one? |
| `strategies.md` | arv | v0.1 | What does each baseline do? |
| `scoring.md` | arv | v0.2 | What does each score mean, and how is it computed? |
| `benchmark-statistics.md` | arv | v0.3 | What do repeated runs look like, summarised? |
| `statistics.md` | arv | v0.4 | Why these tests, and how do I read the output? |
| `../README.md` | jv | v0.1, finished in v1.0 | What is this, and how do I see it work in five minutes? |
| `../CONTRIBUTING.md` | jv | v0.1 | How do I propose a change? |
| `cli.md` | jv | v0.2 to v0.4 | What commands and options exist? |

Pages appear here as their release lands. As of v1.0 these exist:
`simulator.md`, `event-format.md`, `scoring.md`, `cli.md`,
`architecture.md`, `concepts.md`, `trust-model.md`, `strategies.md`,
`attacks.md`, `benchmark-statistics.md`, `statistics.md` (confidence
intervals so far), `results.md`, `extending.md` (custom attacks and your own system so far), `../INSTALL.md` (with its Mininet section
from v1.0), `../backends/mininet/README.md`, `../README.md` and
`../CONTRIBUTING.md`. Each attack's entry in `attacks.md` is written by its
author.
