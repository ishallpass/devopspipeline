# Git Hook Test Cases

These artifacts prove that the local Git hooks (`.git-hooks/pre-commit` and
`.git-hooks/pre-push`) actually block insecure changes. Use them to capture
screenshots for the technical report.

> Prerequisite: hooks must be installed in this repo:
> ```bash
> ./install-hooks.sh    # sets core.hooksPath to .git-hooks/
> ```

---

## 1. pre-commit — hardcoded secret detection

The pre-commit hook scans the **staged diff** for secret assignments
(`password`, `secret`, `api_key`, `access_key`, `token`, private keys).

```bash
# sample-secret.txt is git-ignored, so force-add it:
git add -f docs/hook-tests/sample-secret.txt
git commit -m "attempt to commit a secret"
```

Expected result: the commit is **rejected** with
`ERROR: possible hardcoded secret in staged changes:` and the offending lines.

Clean up:

```bash
git reset docs/hook-tests/sample-secret.txt
```

To show the override path (and explain why it exists), mention:
`git commit --no-verify` bypasses the hook intentionally.

---

## 2. pre-commit — malformed YAML detection

The pre-commit hook runs `yamllint` on every YAML file (skipped automatically
if `yamllint` is not installed — `pip install yamllint`).

```bash
cp docs/hook-tests/broken-config.yml.example broken-config.yml
git add -f broken-config.yml
git commit -m "attempt to commit broken yaml"
```

Expected result: the commit is **rejected** — `yamllint` reports the bad
indentation / duplicate keys, and the secret line also trips check #1.

Clean up:

```bash
git reset broken-config.yml && rm broken-config.yml
```

---

## 3. pre-push — required pipeline file missing

The pre-push hook refuses to push if `Jenkinsfile`, `configs/semgrep.yml`, or
`targets/endpoints.txt` is missing.

```bash
git mv Jenkinsfile Jenkinsfile.bak
git commit -m "temporarily remove Jenkinsfile"
git push            # rejected: "ERROR: Jenkinsfile not found (Jenkinsfile)"
```

Clean up:

```bash
git mv Jenkinsfile.bak Jenkinsfile
git commit -m "restore Jenkinsfile"
```

---

## 4. pre-push — invalid docker-compose

The pre-push hook validates `docker-compose.yml` with `docker compose config`.

```bash
cp docker-compose.yml docker-compose.yml.bak
printf '\n  bad_indent: [' >> docker-compose.yml   # break the YAML/compose
git add docker-compose.yml && git commit -m "break compose"
git push            # rejected during validate_compose
```

Clean up:

```bash
mv docker-compose.yml.bak docker-compose.yml
git add docker-compose.yml && git commit -m "restore compose"
```

---

## Notes

- `sample-secret.txt` is git-ignored on purpose: a repo protected by the secret
  hook should never carry a committed secret. Force-add (`git add -f`) only for the demo.
- `broken-config.yml.example` uses a `.example` extension so it does not get
  auto-linted on every commit (the hook lints all `*.yml`/`*.yaml` on disk).
