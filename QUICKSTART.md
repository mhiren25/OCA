# Quickstart

## Once

```bash
cd trade-capture-agent
cp pip.conf.template pip.conf         # set your Nexus URL
./init.sh
source .venv/bin/activate
ln -sf ../../scripts/hooks/pre-commit .git/hooks/pre-commit
$EDITOR CODEOWNERS                    # replace @REPLACE-ME

npm install -g --registry "$NPM_REGISTRY" @fission-ai/openspec
openspec init
openspec config profile               # choose EXPANDED
openspec update

copilot plugin marketplace add obra/superpowers-marketplace
copilot plugin install superpowers@superpowers-marketplace
```

Check:

```bash
pytest                  # green   ← baseline
pytest -m acceptance    # red     ← the target
```

Both are correct.

---

## Per change — 001 first

**1. Create it** (in `copilot`)

```
/opsx:new 001-capture-model-types
```

**2. Add the proposal, generate the rest**

```bash
cp docs/proposals/001-capture-model-types.md \
   openspec/changes/001-capture-model-types/proposal.md
```

```
/opsx:ff
```

**3. Read `proposal.md` and `tasks.md`. Then approve.**

```bash
cp docs/proposals/_approval-template.yaml \
   openspec/changes/001-capture-model-types/approval.yaml
$EDITOR openspec/changes/001-capture-model-types/approval.yaml
git add -A && git commit -m "approve 001-capture-model-types"
```

**4. Build**

```
Use subagent-driven-development to implement
openspec/changes/001-capture-model-types/.
Baseline is `pytest`; target is `pytest -m acceptance`.
tests/acceptance/ is read-only. Most capable model for the final review.
```

If it makes a worktree: `scripts/seed-worktree.sh .worktrees/<branch>`

**5. Verify**

```bash
pytest -m acceptance
pytest
git diff --stat
```

```
/opsx:verify
```

**6. Close**

```
/opsx:sync
/opsx:archive
```

---

## Order

`001` → `002` → **stop and judge the workflow** → then 007, 008, 006+009,
010, 013 → label fixtures → tune.

For 002, swap step 4 for `/opsx:apply` — it's small enough.

Detail in `docs/first-tasks.md`. Rules in `docs/workflow.md`.
