# Codex Upgrade Reports

Each Codex source code upgrade must save an independent report in this directory. The file name format is:

```text
YYYYMMDD-codex-vX.Y.Z.md
```

Before pulling, create a report containing the previous Codex CLI version, source commit, and Codex-Rosetta version and commit. After pulling, add the target Codex release and new source commit.

Each report contains at least:

1. Old/new Codex CLI version, source code commit, date and Codex-Rosetta version/commit;
2. Three types of contract-group output of `make check-codex-compat`;
3. An itemized classification of every compatibility point in `../compatibility-points.md`, with the same number of entries as the source list;
4. The repair plan and results of each "changed" item;
5. All automated test commands and results;
6. Real API test models, routes, scenarios and results for each "may not change" or "change" item;
7. Unresolved limitations, whether upgrades are allowed, and final Codex-Rosetta package version.

Use the itemized classification table:

| Compatibility points | Classification | Source code/contract evidence | Fix or review plan | Automation results | Real API results |
| --- | --- | --- | --- | --- | --- |
| `<Copied from compatibility-points.md>` | High-confidence unchanged / possibly unchanged / changed | `<evidence>` | `<plan>` | `<command and results>` | `<model, route and results>` |

High-confidence unchanged rows may record the live API result as "not triggered this time", but their live scenarios must remain defined in `../compatibility-points.md`. Possibly unchanged and changed rows require live API results; mocks or fixtures cannot replace them.
