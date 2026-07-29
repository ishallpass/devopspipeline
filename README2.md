# Automated DevSecOps Pipeline (Git Hooks + Jenkins + Docker)

An automated **DevSecOps pipeline** that runs security and quality checks on every
Git commit/push. Local Git hooks perform fast checks, and a **Jenkins** CI/CD
pipeline orchestrates the full set of **static** and **dynamic** security scans,
all executed inside **Docker** containers. Results are consolidated into a single
Markdown report.

The target application under test is [OWASP Juice Shop](https://github.com/juice-shop/juice-shop),
a deliberately vulnerable Node.js/TypeScript web app, used strictly in an isolated
local environment for educational purposes.

---

## Table of contents

- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Security checks](#security-checks)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Running the pipeline (Jenkins)](#running-the-pipeline-jenkins)
- [Running scans locally (no Jenkins)](#running-scans-locally-no-jenkins)
- [Git hooks](#git-hooks)
- [Reports](#reports)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
Developer machine                         Jenkins (Docker container)
─────────────────                         ───────────────────────────
git commit ──► pre-commit hook            ┌───────────────────────────────┐
  (secret scan + YAML lint)               │ Stage 1: Checkout              │
                                          │   clone pipeline repo + app    │
git push  ──► pre-push hook  ──trigger──► │ Stage 2: Static Analysis       │
  (validate + notify Jenkins)             │   Gitleaks / Semgrep /         │
                                          │   Trivy FS / njsscan           │
                                          │ Stage 3: Build & Deploy        │
                                          │   docker build + run app       │
                                          │ Stage 4: Dynamic Analysis      │
                                          │   Trivy image / ZAP / Nmap /   │
                                          │   endpoint tests               │
                                          │ Stage 5: Report                │
                                          │   generate-report.py           │
                                          └───────────────────────────────┘
                                                        │
                                                        ▼
                                              reports/final_report.md
```

Every tool runs as a short-lived Docker container. Jenkins itself runs in a
container and talks to the host Docker daemon via the mounted Docker socket.

## Repository layout

| Path | Purpose |
|------|---------|
| `Jenkinsfile` | Declarative Jenkins pipeline (all stages) |
| `start-pipeline.sh` | Boots Jenkins in Docker, pre-installs plugins, creates the job |
| `run-local-scan.sh` | Runs the static scans locally without Jenkins |
| `docker-compose.yml` | Compose definition mirroring the scan tools |
| `.git-hooks/pre-commit` | Fast local checks: secret scan + YAML lint |
| `.git-hooks/pre-push` | Pre-push validation + Jenkins build trigger |
| `install-hooks.sh` | Points `core.hooksPath` at `.git-hooks/` |
| `configs/semgrep.yml` | Custom Semgrep rules (JS/TS security smells) |
| `targets/endpoints.txt` | Endpoints exercised by the dynamic checks |
| `scripts/generate-report.py` | Aggregates tool outputs into `reports/final_report.md` |
| `tests/` | Pytest suite for the report aggregator |
| `reports/` | Generated scan outputs (git-ignored) |

## Security checks

### Static analysis (source code)

| Category | Tool | Why |
|----------|------|-----|
| Secret scanning | **Gitleaks** | Detects hardcoded credentials, tokens, private keys |
| SAST | **Semgrep** (`p/javascript`, `p/nodejs`, `p/owasp-top-ten` + custom rules) | Broad JS/Node coverage plus rules targeting the injected vulnerabilities |
| Node.js SAST | **njsscan** | Node/Express-specific security smells (replaces Python-only Bandit) |
| Dependency scanning | **Trivy (fs)** | Known-vulnerable npm dependencies |

### Dynamic analysis (running app / container)

| Category | Tool | Why |
|----------|------|-----|
| Container image vulns | **Trivy (image)** | Scans the built Docker image for CVEs |
| DAST | **OWASP ZAP** (baseline) | Black-box web scan of the running app |
| Port scanning | **Nmap** | Enumerates exposed ports/services |
| Endpoint testing | **curl** | Probes the endpoints declared in `targets/endpoints.txt` |

## Prerequisites

- **Docker** with a Linux daemon exposing a Unix socket at `/var/run/docker.sock`.
  Any of the following works:
  - Docker Engine on Linux
  - **Rancher Desktop** in `dockerd (moby)` mode (used during development)
  - Docker Desktop
- A **Bash** environment (Linux, macOS, WSL2, or the shell inside a WSL distro).
- `git`, `curl`.

> **Windows note:** `start-pipeline.sh` is a Bash script and assumes a Linux
> Docker host. Run it from WSL2 / a Linux distro that has access to your Docker
> daemon. See [Troubleshooting](#troubleshooting) for Rancher Desktop specifics.

## Quick start

```bash
# 1. Install the Git hooks (once, after cloning)
./install-hooks.sh

# 2. Boot Jenkins and auto-create the pipeline job
./start-pipeline.sh

# 3. Open Jenkins
#    http://localhost:8081  (job: DevSecOps-Pipeline)
```

## Running the pipeline (Jenkins)

`start-pipeline.sh`:

1. Pre-installs the required Jenkins plugins into the `jenkins_home` volume.
2. Starts Jenkins (`jenkins/jenkins:lts-jdk21`) on port **8081**, mounting the
   host Docker socket so pipeline stages can launch tool containers.
3. Installs the Docker CLI inside the Jenkins container.
4. Creates the `DevSecOps-Pipeline` job (pointed at this repo's `Jenkinsfile`)
   and triggers the first build.

Watch the build at:
`http://localhost:8081/job/DevSecOps-Pipeline/lastBuild/console`

Environment overrides:

| Variable | Default | Meaning |
|----------|---------|---------|
| `JENKINS_HOST_PORT` | `8081` | Host port for the Jenkins UI |
| `JENKINS_IMAGE` | `jenkins/jenkins:lts-jdk21` | Jenkins image |
| `REPO_URL` | auto-detected from `git remote` | Repo Jenkins clones |

## Running scans locally (no Jenkins)

For a fast local run of the static scans:

```bash
./run-local-scan.sh
# Reports are written to ./reports/
```

Or via Docker Compose (each service is one scanner):

```bash
docker compose run --rm gitleaks
docker compose run --rm semgrep
docker compose run --rm trivy
docker compose run --rm njsscan
docker compose run --rm zap      # requires the app running on :3000
```

## Git hooks

Install with `./install-hooks.sh` (sets `core.hooksPath` to `.git-hooks/`).

- **pre-commit** — blocks commits containing likely hardcoded secrets and lints
  YAML files (when `yamllint` is installed). Override intentionally with
  `git commit --no-verify`.
- **pre-push** — validates that the pipeline definition and required config/target
  files exist and that `docker-compose.yml` is valid, then triggers a Jenkins
  build (see [Configuration](#configuration)).

The split is deliberate: **fast, high-signal checks run locally** (secrets,
linting) to give immediate feedback, while the **heavier, slower scans run in
Jenkins** where they don't block the developer.

## Reports

- Per-tool outputs land in `reports/` (e.g. `gitleaks.json`, `semgrep.json`,
  `trivy-fs.json`, `njsscan.json`, `nmap.txt`, `zap-report.html`,
  `endpoint-test.txt`).
- `scripts/generate-report.py` consolidates them into
  **`reports/final_report.md`** with an executive summary, severity breakdown,
  per-tool counts and a findings table.
- The `reports/` contents are git-ignored; commit copies (or screenshots) as
  submission artifacts if needed.

Run the aggregator's tests:

```bash
python -m pytest tests/ -v
```

## Configuration

- **Semgrep rules:** `configs/semgrep.yml`
- **Dynamic endpoints:** `targets/endpoints.txt`
- **Jenkins trigger token** (used by the `pre-push` hook): set `JENKINS_URL`
  (default `http://localhost:8081`) and `JENKINS_BUILD_TOKEN`
  (default `devsecops`) in your environment before pushing.

## Troubleshooting

**Rancher Desktop (Windows):** set Container Engine to `dockerd (moby)` and quit
Docker Desktop so the CLI binds to Rancher. From the WSL distro that hosts
Rancher's daemon you get `/var/run/docker.sock`, `/mnt/c`, `git` and `docker`.

**CRLF line endings:** if scripts fail with `set: pipefail: invalid option name`,
the files have Windows line endings. Normalize with `git config core.autocrlf`
handling or strip them: `tr -d '\r' < script.sh > script.unix.sh`.

**Docker credential helper errors** (`error getting credentials ... exit status`):
point `DOCKER_CONFIG` at a clean directory: `mkdir -p /tmp/dockercfg && echo '{}'
> /tmp/dockercfg/config.json && export DOCKER_CONFIG=/tmp/dockercfg`.

**TLS `certificate signer not trusted`** (corporate proxy): for a local lab you
can disable git TLS verification inside Jenkins — `start-pipeline.sh` sets
`GIT_SSL_NO_VERIFY=true` and `git config --system http.sslVerify false`. Do **not**
do this outside an isolated environment.
