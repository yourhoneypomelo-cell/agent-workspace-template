# Template checkout

This folder is the source of the workspace template, not a project.
Projects never receive this file. `ws tidy` and the leftover check in `ws check` skip a folder that has it.

| Maintainer file | Holds |
| --- | --- |
| [MAINTAINING.md](guides/MAINTAINING.md) | Self-tests, release steps, version history, reviews |
| [DESIGN_REQUIREMENTS.md](guides/DESIGN_REQUIREMENTS.md) | What the template must achieve and why |
| `tools/tests/` | Self-tests, run from `.agents/tools` |
| `template/examples/minimal_cycle.py` | A scripted session that maintainers run as a smoke test |
