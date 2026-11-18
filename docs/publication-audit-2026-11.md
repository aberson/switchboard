# Switchboard publication audit (2026-11)

Status: Step 12 of the V4-10 core companion plan (issue #291 in the private coding-root). This
report owns the private-data findings for publishing `switchboard/` as its own public
repository, the disposition of each finding, and the exact split method that Step 13 runs.
Nothing was published in Step 12: no push, no repository creation, no remote.

The input evidence was the lane's read-only inventory (`docs/research/switchboard-publication-inventory-2026-11-18.md`
in the private coding-root, findings F1-F11) and the operator decisions recorded at its top on
2026-11-18. Every inventory finding was re-scanned here; the IDs below keep the inventory's F-number
where one exists.

## 1. Operator decisions cited

| Decision | Words (relayed 2026-11-18, "1a 2a 3a 4a 5a") |
|---|---|
| 1a | Keep the author e-mail. |
| 2a | Keep the void_furnace names; replace the Linux host home path. |
| 3a | Drop `docs/archived-plans/workspace-docs/switchboard-phase-2-plan.md` from the published history. |
| 4a | Keep the dev-observatory name. |
| 5a | Publish the planning records with the path fixes applied. |
| CC-D11 | (core companion plan) The registry and `apply` join the core ring at the public split. |

## 2. Scope and method

- **History.** `git log --all -p --format='COMMIT %H%n%B%nENDMSG' -- switchboard/` from the
  coding-root, written to a temp file (4.8 MB): 57 commits touch the path across all refs.
  **38 of them are on `master`**, the only branch the split publishes; the other 19 sit only on
  rescue, feature and stash refs and are excluded by the clone scope (finding A23). Commit
  messages were scanned as well as file content (added and removed lines).
- **Tip.** The 73 tracked files under `switchboard/` at the Step 12 base, plus the files this
  step adds.
- **Patterns.** Absolute personal paths in every form (Windows with `\`, `/` and JSON-escaped
  `\\`; WSL `/mnt/<drive>/Users/...`; Git Bash `/<drive>/Users/...`; Linux `/home/<user>`;
  macOS `/Users/<user>`; the host's project-folder slug form `<drive>--Users-<account>`); the
  Windows account name as a bare word; the author's real name and GitHub handle; e-mail
  addresses; this machine's hostname and `DESKTOP-`/`LAPTOP-` names; IPv4 addresses; URLs and
  `localhost` ports; `.claude/projects` and `AppData` references; worktree folder names;
  key-shaped strings (`sk-`, GitHub, AWS, Slack, PEM, bearer, `key|token|secret|password =`
  assignments, and any 40+ character token-like run). Key-shaped values were masked in every
  scan output and never printed. Every other project folder of the coding-root was matched as a
  whole word, case-insensitive, and each hit's GitHub visibility was checked with `gh repo view`
  on 2026-11-18.
- **Binary content.** `git log --all --numstat -- switchboard/` shows no binary file in the
  path history, so the text scan covers every blob.
- **Not covered here.** Remote surfaces (issues, pull requests, releases, settings) of the
  private coding-root repository: none of them moves with the split, and the new repository
  starts with none (A26).

## 3. Findings and dispositions

Counts are occurrences in `master` history unless marked "all refs". "History expression"
means the split rewrites every commit with that `--replace-text` / `--replace-message`
expression (section 4, block 2); the rehearsal (section 5) proves zero remaining matches.

| ID | Finding | Where (paths inside `switchboard/`) | Disposition |
|---|---|---|---|
| A1 (F1) | Author name and personal e-mail on every commit; the 4 merge commits carry the GitHub web-flow committer | commit metadata, 38 commits | **Accepted risk**, decision 1a: the same identity the other public repositories already carry. No `--mailmap`. Note for the re-read: the Windows account name is a prefix of the e-mail's local part, so it stays inferable from the commit identity even though A2-A7 remove it from all content. |
| A2 (F2) | Windows personal paths `<drive>:\Users\<account>\dev...` (back-slash, forward-slash and JSON-escaped forms) | `docs/plans/master_plan.md` (17 account-name hits), `docs/archived-plans/workspace-docs/switchboard-tune-plan.md` (3 + WSL forms), `docs/plans/model-registry-handoff-blocks.md` (1), `docs/seeds/seed_home_guard_remaining_sites.md` (1), `docs/seeds/seed_r7_deep_research_role_dispatch.md` (1), the dropped plan (1); 5 commits | **Fixed in history**: E1 (under `dev` becomes `<coding-root>`), then E2 (any other becomes `<home>`). Decision 5a. |
| A3 (F2) | WSL personal paths `/mnt/<drive>/Users/<account>/dev/...` | `docs/plans/master_plan.md` (6), `docs/archived-plans/workspace-docs/switchboard-tune-plan.md` (6); 1 commit | **Fixed in history**: E3, E4. |
| A4 | Git Bash form `/<drive>/Users/<account>` | none found | **Fixed in history** as defence: E5, E6. |
| A5 | Project-folder slug form `<drive>--Users-<account>` | none personal; 3 hits are the `someone` placeholder in `tests/test_observe.py` | **Fixed in history** as defence: E7. The placeholder fixtures are excluded so the tests still pass. |
| A6 (F3) | Linux host home path `/home/<user>/...` naming the WSL account (the void_furnace runtime installer path) | `scripts/start-offload.ps1` on the unpublished endpoint-launcher branch only (2, all refs); 0 on `master` | **Fixed in history** by the clone scope (A23); E8 rewrites any later occurrence to `~/`. Decision 2a. |
| A7 | The Windows account name as a bare word outside a path | none: every occurrence is inside an A2/A3 path | **Fixed in history** with A2/A3; the rehearsal counts the bare word too. |
| A8 (F4) | Plan for a third party's private repository | `docs/archived-plans/workspace-docs/switchboard-phase-2-plan.md` | **Fixed in history**: removed from every commit (block 2, second `filter-repo` pass, `--invert-paths --path`). Decision 3a. |
| A9 (F4, new) | That plan's content was also migrated into other records, so after A8 the third-party project name (and its owner's GitHub handle) still appear | `docs/plans/master_plan.md` (37), `docs/plan-reconciliation/parsed-units.json` (45), `docs/plan-reconciliation/source-map.md` (2), `docs/plan-reconciliation/proposal.html`, `review.md`, `wrap.md` (1 each); handle in `master_plan.md` and `parsed-units.json` (5); 2 commits | **Fixed in history**: P1 (handle becomes `<friend-owner>`) and P2 (name becomes `<friend-project>`). Neither literal is written in any published file: block 2 reads both from the dropped plan's `remote <owner>/<project>` line at split time and keeps the expression file outside the repository. This extends 3a to the same content; **Step 13 re-read**: the operator may instead drop the migrated P1-P7 records. |
| A10 (F3) | Private project void_furnace named (no code or data from it) | `switchboard/bakeoff.py`, `CLAUDE.md`, `docs/plans/master_plan.md`, `docs/archived-plans/workspace-docs/switchboard-offload-phase-b-plan.md`, `docs/plan-reconciliation/parsed-units.json` (58 at the tip); 4 commits | **Accepted risk**, decision 2a. |
| A11 (F6) | Private project dev-observatory named | `docs/plans/master_plan.md`, `docs/seeds/seed_dispatch_proof.md`, `docs/archived-plans/...`, 5 commit messages (65 at the tip); 11 commits | **Accepted risk**, decision 4a. |
| A12 (F6) | Public projects named: skill-mesh, measure-twice, tripwire, Alpha4Gate, toybox, pta_finance | docs, `switchboard/config.py`, `switchboard/registry.py`, `registry/models.json`, `tests/test_observe.py` | **Accepted**: each is a public repository (checked 2026-11-18). |
| A13 | Other private names, mention only: the private coding-root repository (in planning records and one commit message), the judge-motion skill (registry role `motion-judge` description and plans), the private utility-project-standard (this report's block 0 and the `utility-project.toml` convention, CC-D9), and the GitHub handle in 4 merge-commit subjects | docs, `registry/models.json`, commit messages | **Accepted risk** under 1a (the handle is the public identity of A1) and 4a by analogy (private names kept, no content). **Step 13 re-read.** `goblin-*` hits name the retired public skill-mesh skills, not a private repository. |
| A14 (F7) | Key-shaped strings | fake `sk-` values and a token-shaped fixture in `tests/test_native_dispatch.py` (unpublished rescue ref only); 40+ character runs are `uv.lock` URLs and hashes, test names and SHA-256 fixtures | **Accepted**: test fixtures and public package hashes; no real credential in any ref. |
| A15 (F8) | Endpoints: `localhost:8080` (the documented llama-swap default), `localhost:9090` and `judge.internal:8443` (test fixtures), `127.0.0.1` (a delay in a fake-native fixture on the rescue ref); public hosts only otherwise (pypi.org, files.pythonhosted.org, docs sites) | `README.md`, `CLAUDE.md`, `switchboard/config.py`, `run_shadow_live.py`, tests | **Accepted**: the product's documented local default; no private network address. `utility-standard audit-publication` reports loopback forms by rule (section 6). |
| A16 | `.claude/projects` references | `switchboard/observe.py`, `README.md`, `registry/models.json` evidence notes, `tests/test_observe.py` (19) | **Accepted**: the host's generic transcript folder that `observe` reads by design; no personal path. |
| A17 | Registry role descriptions and evidence notes (14 roles) | `registry/models.json` | Reviewed line by line. Descriptions name skill-mesh skills (public), the retired goblin-suggest skill, the judge-motion skill (A13) and operator decision IDs. Evidence notes carry aggregate counts from a 30-day local transcript scan (model IDs and transcript counts only): no path, content or identity. **Accepted**: CC-D11 publishes the registry as the default routing policy; the counts are non-identifying aggregates. |
| A18 (F9) | Machine names and private IPs | none (this machine's hostname: 0; `DESKTOP-`/`LAPTOP-`: only the word `desktop-icon`) | None needed. |
| A19 (F10) | README named skill-mesh's `config/spawn-sites.json`, which does not exist | `README.md` (`apply` options and advisory lines), `switchboard/generate.py` (docstring, comment) | **Fixed at the tip** in Step 12: the catalog is now described as a caller-supplied file, and the README says no catalog ships anywhere today. |
| A20 | README linked `../docs/investigations/switchboard-spike.md`, outside `switchboard/` (dead after the split) | `README.md` | **Fixed at the tip**: the README opening was rewritten (overview, why, install, quick start, verification, platforms, license). Docstrings in `switchboard/__init__.py`, `switchboard/client.py`, `tests/conftest.py` and the planning records still cite coding-root documents and issue numbers: **accepted** as dangling references with no content (5a). |
| A21 (F11) | Planning records with workspace context | `docs/plans/`, `docs/archived-plans/`, `docs/plan-reconciliation/`, `docs/seeds/`, `docs/repo-update/` | **Accepted**, decision 5a, with A2-A9 applied. |
| A22 (F5) | `offload-scan-out` | `README.md` | **Accepted**: a generic example output folder. |
| A23 | 19 commits touching `switchboard/` exist only on rescue, feature and stash refs; they carry A6, a worktree path in one commit message, and A14's fixtures | other refs (all refs only) | **Fixed by the split's clone scope**: `git clone --single-branch --branch master`, so none of those refs is cloned. |
| A24 | Commit messages | 38 `master` messages | No personal path or account name found. They cite coding-root issue and PR numbers, lane note IDs and co-author trailers: **accepted** (5a). `--replace-message` applies the same expressions as defence. |
| A25 | No license existed | project root | **Fixed at the tip**: MIT `LICENSE` ("switchboard contributors") and `license = "MIT"` in `pyproject.toml`, matching the other public utilities. **Step 13 re-read**: the license is an outward-facing choice. |
| A26 | Remote surfaces | GitHub | The new repository starts with no issues, pull requests or releases; the coding-root's stay private. `remote_audit = false` in `utility-project.toml`. Step 13 checks the new repository's settings before the visibility flip. |

**Accepted risks for the Step 13 re-read**: A1, A9's variant choice, A10, A11, A13, A17, A25.

## 4. Split method (Step 13 runs these blocks in order)

The default from the plan: `git filter-repo --subdirectory-filter switchboard` on a fresh
clone, with `--replace-text` for the history findings. `git filter-repo` is installed, so the
`git subtree split` fallback is not needed. Run in Windows PowerShell 5.1. Each block is
ASCII-only and is the exact text the rehearsal ran (section 5).

Block 0 sets the inputs. The two angle-bracket values are the only edits.

<!-- split-block: 0 -->
```powershell
$CodingRoot   = '<coding-root checkout>'                # the private coding-root, on master
$StandardRoot = '<utility-project-standard checkout>'   # for the conformance check
$Work = Join-Path $env:TEMP 'switchboard-split'         # must not exist yet
```

Block 1 makes a fresh single-branch clone and removes its only remote, so nothing in the
rewrite can be pushed by accident.

<!-- split-block: 1 -->
```powershell
function Invoke-Git { & git @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed: $LASTEXITCODE" } }
$Repo = Join-Path $Work 'switchboard'
New-Item -ItemType Directory -Path $Work -ErrorAction Stop | Out-Null
Invoke-Git clone --no-local --single-branch --branch master $CodingRoot $Repo
Invoke-Git -C $Repo remote remove origin
if (@(git -C $Repo remote).Count -ne 0) { throw 'the disposable clone still has a remote' }
```

Block 2 writes the expressions outside the repository, then rewrites in two passes. Both
passes need `--force`: filter-repo's fresh-clone check expects an `origin` remote, which block 1
removes on purpose, and after the first pass the clone is no longer fresh anyway. Block 1 is
what guarantees a fresh clone. The `--path` filter cannot share the first pass, since
`--invert-paths` would also invert the subdirectory filter.

<!-- split-block: 2 -->
```powershell
$Before = @(git -C $Repo log --format= --name-only -- switchboard/ | Where-Object { $_ } | ForEach-Object { $_.Substring(12) } | Sort-Object -Unique)
# E1-E8: generic expressions (Python regexes, applied in order). The placeholder fixtures
# `someone` and `test` are left alone so the test suite still passes.
$Public = @'
regex:[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+(?!(?:someone|test)(?![A-Za-z0-9]))[^\\/\s"'`<>]+(?:\\\\|\\|/)+dev(?![A-Za-z0-9_-])==><coding-root>
regex:[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+(?!(?:someone|test)(?![A-Za-z0-9]))[^\\/\s"'`<>]+==><home>
regex:/mnt/[a-z]/Users/(?!(?:someone|test)/)[^/\s"'`<>]+/dev(?![A-Za-z0-9_-])==><coding-root>
regex:/mnt/[a-z]/Users/(?!(?:someone|test)/)[^/\s"'`<>]+==><home>
regex:(?<![A-Za-z0-9_.-])/[a-z]/Users/(?!(?:someone|test)/)[^/\s"'`<>]+/dev(?![A-Za-z0-9_-])==><coding-root>
regex:(?<![A-Za-z0-9_.-])/[a-z]/Users/(?!(?:someone|test)/)[^/\s"'`<>]+==><home>
regex:(?<![A-Za-z0-9])[A-Za-z]--Users-(?!(?:someone|test)(?![A-Za-z0-9]))[A-Za-z0-9]+==><home-slug>
regex:/home/(?!(?:someone|test)/)[A-Za-z0-9._-]+/==>~/
'@
# P1-P2: the third-party names (A9), read from the private history at split time so that no
# published file carries them.
$Plan = (git -C $Repo show 'HEAD:switchboard/docs/archived-plans/workspace-docs/switchboard-phase-2-plan.md') -join "`n"
$Remote = [regex]::Match($Plan, 'remote `([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)`')
if (-not $Remote.Success) { throw 'could not read the third-party remote from the dropped plan' }
$Private = @(
    "regex:(?i)(?<![A-Za-z0-9])$([regex]::Escape($Remote.Groups[1].Value))(?![A-Za-z0-9])==><friend-owner>",
    "regex:(?i)(?<![A-Za-z0-9])$([regex]::Escape($Remote.Groups[2].Value))(?![A-Za-z0-9])==><friend-project>"
)
$Expressions = Join-Path $Work 'expressions.txt'
$Lines = @($Public -split "`r?`n" | Where-Object { $_ }) + $Private
[System.IO.File]::WriteAllText($Expressions, (($Lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
Invoke-Git -C $Repo filter-repo --force --subdirectory-filter switchboard --replace-text $Expressions --replace-message $Expressions
Invoke-Git -C $Repo filter-repo --force --invert-paths --path docs/archived-plans/workspace-docs/switchboard-phase-2-plan.md
```

Block 3 proves the history: only `switchboard/` paths, the dropped plan in no commit, and zero
matches for every expression plus the bare account name, over all commits, all blobs and all
messages.

<!-- split-block: 3 -->
```powershell
$After = @(git -C $Repo log --all --format= --name-only | Where-Object { $_ } | Sort-Object -Unique)
$Dump = Join-Path $Work 'rewritten-history.patch'
Invoke-Git -C $Repo log --all -p --format='COMMIT %H%n%an <%ae>%n%cn <%ce>%n%B' "--output=$Dump"
$Text = [System.IO.File]::ReadAllText($Dump)
$Checks = [ordered]@{}
$Index = 0
foreach ($Line in [System.IO.File]::ReadAllLines($Expressions)) {
    $Index++
    $Label = if ($Index -le 8) { "E$Index" } else { "P$($Index - 8)" }
    $Checks[$Label] = [regex]::Matches($Text, $Line.Substring(6, $Line.LastIndexOf('==>') - 6)).Count
}
$Checks['account-name'] = [regex]::Matches($Text, "(?i)(?<![A-Za-z0-9])$([regex]::Escape($env:USERNAME))(?![A-Za-z0-9])").Count
"commits: $(git -C $Repo rev-list --all --count)"
"refs: $(@(git -C $Repo for-each-ref --format='%(refname)') -join ', ')"
"remotes: $(@(git -C $Repo remote).Count)"
"paths outside the switchboard/ history: $(@($After | Where-Object { $Before -notcontains $_ }).Count)"
"dropped plan in a commit: $(@($After | Where-Object { $_ -like '*switchboard-phase-2-plan.md' }).Count)"
"dropped plan in an object path: $(@(git -C $Repo rev-list --all --objects | Where-Object { $_ -like '*switchboard-phase-2-plan.md' }).Count)"
$Checks.GetEnumerator() | ForEach-Object { "fixed-pattern matches $($_.Key): $($_.Value)" }
"fixed-pattern matches total: $(($Checks.Values | Measure-Object -Sum).Sum)"
```

Block 4 proves the rewritten tip still works and still conforms.

<!-- split-block: 4 -->
```powershell
Push-Location $Repo
try {
    uv sync --extra dev
    uv run pytest
    "pytest exit: $LASTEXITCODE"
    uv run switchboard --version
} finally { Pop-Location }
uv run --project $StandardRoot utility-standard check $Repo
```

Step 13 then creates the public repository from `$Repo`, pushes `master`, and tags `v0.1.0`
(operator step; not part of Step 12). Re-read the accepted risks in section 3 before the
visibility flip.

## 5. Rehearsal (2026-11-18)

Run on 2026-11-18 by the Step 12 developer with git-filter-repo `a40bce548d2c` in Windows
PowerShell 5.1, under a disposable folder in the system temp directory.

- **Rehearsal-only setup.** A staging clone of the coding-root `master` (single branch, remote
  removed immediately after cloning) received the Step 12 working tree's 77 `switchboard/` files
  in one commit, so the rewrite also covers this step's own files, this report included. Block 0
  pointed `$CodingRoot` at that staging clone. Blocks 1-4 were extracted from this file by their
  `split-block` markers and run unedited.
- **First attempt.** It stopped in block 2: filter-repo refused a clone with no `origin` remote
  ("does not look like a fresh clone"). Block 2 now passes `--force` on both passes; the second
  attempt started again from an empty folder.
- **Output** of blocks 3 and 4, verbatim except that the per-expression lines are folded into one:

```
commits: 39
refs: refs/heads/master
remotes: 0
paths outside the switchboard/ history: 0
dropped plan in a commit: 0
dropped plan in an object path: 0
fixed-pattern matches E1-E8, P1, P2, account-name: 0 each
fixed-pattern matches total: 0
376 passed, 2 skipped
pytest exit: 0
switchboard 0.1.0
PASS: cc-s12-split/work/switchboard
summary: 0 error, 0 warning, 0 info
```

- **Commit count.** 39 = the 38 `master` commits that touch `switchboard/`, plus the rehearsal's
  overlay commit. Step 13 should see 38 plus the commit that lands Step 12 (and any later
  `switchboard/` commits).
- **Independent cross-check** (not using the expressions). The rewritten history dump (1.38 MB,
  every commit, blob diff and message) was rescanned with the section 2 pattern scan and with
  literal, case-insensitive, whole-word searches for the account name, the third-party project
  name, its owner's handle, the Linux host home path and this machine's hostname: 0 each. The
  path patterns still hit only the `someone` placeholder fixtures in `tests/test_observe.py`,
  the `C:\fixture\project` fixtures in `tests/fixtures/observe/`, and this report's generic
  descriptions. The replacement tokens appear where expected (`<coding-root>\switchboard`,
  `<coding-root>/switchboard-tune`, `<home>/.switchboard/...`, `<friend-project>`,
  `<friend-owner>`). The only remaining trace of the account name is A1's identity lines (72).
- **Clean-up.** The disposable folder (staging clone, rewritten clone, expressions file and
  dump) was deleted after these results were recorded. No remote existed after cloning, and
  nothing was pushed.

## 6. Conformance

- **Check.** From the coding root, `uv run --project <utility-project-standard checkout> utility-standard check <path to switchboard>`,
  and in the plan's form from the directory that holds `switchboard/`:
  `uv run --project <utility-project-standard checkout> utility-standard check switchboard`.
  Both print `PASS: switchboard` and `summary: 0 error, 0 warning, 0 info` (2026-11-18). The
  rewritten clone passes too (section 5).
- **Declaration.** `utility-project.toml`: `standalone-cli`, `public`, `experimental`, `MIT`;
  README modules `exit-codes` and `development` beyond the core topics; commands
  `uv sync --extra dev`, `uv run switchboard inspect --roles` and `uv run pytest`; platform
  "Windows 11 (Python 3.12+, uv)" verified, with `tests/test_entrypoints.py` as its evidence.
- **Publication audit (information, not a Done-when gate).** `utility-standard audit-publication`
  on the rewritten clone reports `findings` with 147 errors. It is fail-closed by design and
  names only rule IDs and opaque object IDs, so this mapping is by rule pattern, not finding by
  finding: rule 001 (absolute-path shape, 23) and 004 (`Users`/`home` segment, 5) fit the
  placeholder fixtures and this report's generic path descriptions (A5); 002 (loopback host,
  81) and 003 (URL or `--port` with a port, 26) the documented `localhost:8080` endpoint and the
  test fixtures (A15); 005 (`.claude/projects`, 10) the transcript folder (A16); 006
  (secret-shaped path name, 2) the word "token" in a coding-root document name that a planning
  record cites (A20/A21). Each fits an accepted finding; none fits a fixed one. Step 13 re-runs it
  on the final clone.
