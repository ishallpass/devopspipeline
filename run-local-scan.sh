#!/usr/bin/env bash
# Run the DevSecOps security scans locally using Docker (no Jenkins required).
# Produces per-tool reports plus a consolidated report under ./reports/.
set -euo pipefail

readonly EXIT_SUCCESS=0
readonly EXIT_NO_DOCKER=1

readonly REPORTS_DIR="reports"
readonly REPORT_SCRIPT=".git-hooks/security-tools/scripts/generate-report.py"

# Abort early when Docker is unavailable, since every scan depends on it.
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    printf 'ERROR: Docker not found. Install Docker and retry.\n' >&2
    return "${EXIT_NO_DOCKER}"
  fi
}

run_gitleaks() {
  printf 'Running Gitleaks (secret scanning)...\n'
  docker run --rm -v "$(pwd)":/repo zricethezav/gitleaks:latest \
    detect --source="/repo" --report-path="/repo/${REPORTS_DIR}/gitleaks.json" || true
}

run_semgrep() {
  printf 'Running Semgrep (SAST)...\n'
  docker run --rm -v "$(pwd)":/src semgrep/semgrep:latest \
    semgrep --config "p/javascript" --config "p/nodejs" \
            --config "/src/configs/semgrep.yml" /src --json \
    > "${REPORTS_DIR}/semgrep.json" || true
}

run_trivy() {
  printf 'Running Trivy (dependency/filesystem)...\n'
  docker run --rm -v "$(pwd)":/root aquasec/trivy:latest \
    fs /root --format json > "${REPORTS_DIR}/trivy-fs.json" || true
}

run_njsscan() {
  printf 'Running njsscan (Node.js SAST)...\n'
  docker run --rm -v "$(pwd)":/src python:3.11-slim \
    bash -c "pip install --quiet njsscan && njsscan --json -o /src/${REPORTS_DIR}/njsscan.json /src" || true
}

generate_summary() {
  if [[ ! -f "${REPORT_SCRIPT}" ]]; then
    printf 'Report generator not found; reports remain in ./%s/\n' "${REPORTS_DIR}"
    return "${EXIT_SUCCESS}"
  fi
  printf 'Generating consolidated report...\n'
  docker run --rm -v "$(pwd)":/workspace -w /workspace python:3.11-slim \
    python3 "${REPORT_SCRIPT}" || true
}

main() {
  require_docker
  mkdir -p "${REPORTS_DIR}"
  run_gitleaks
  run_semgrep
  run_trivy
  run_njsscan
  generate_summary
  printf 'Local scan complete. Reports are in ./%s/\n' "${REPORTS_DIR}"
  return "${EXIT_SUCCESS}"
}

main "$@"
