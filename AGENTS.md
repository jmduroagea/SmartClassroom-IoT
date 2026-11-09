# Rules for AI assistants in this repository

1. Commits: never commit, push or open pull requests. The human commits
   their own work and writes the PR description in their own words.
2. Decisions: architecture and design decisions belong to the human.
   Before choosing between options (structure, libraries, interfaces,
   MQTT contract, data model), present the options with their trade-offs
   and wait for the human to decide.
3. Architecture rules: respect the specification. The MQTT contract and
   shared constants live in `common/`; no magic numbers; device code only
   talks to the broker; only the brain writes to MongoDB; do not change
   another area's files without saying so first.
4. Tests: every logic change comes with its tests, using the existing
   fakes and stubs. Run the full test suite before saying a task is done.