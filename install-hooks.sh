#!/usr/bin/env bash
# Install this repository's Git hooks by pointing core.hooksPath at .git-hooks.
# Run once after cloning: ./install-hooks.sh
set -euo pipefail

readonly EXIT_SUCCESS=0
readonly EXIT_NOT_A_REPO=1

readonly HOOKS_DIR=".git-hooks"

main() {
  local repo_root
  if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    printf 'ERROR: not inside a Git repository.\n' >&2
    return "${EXIT_NOT_A_REPO}"
  fi
  cd "${repo_root}"

  git config core.hooksPath "${HOOKS_DIR}"
  chmod +x "${HOOKS_DIR}/pre-commit" "${HOOKS_DIR}/pre-push"

  printf 'Git hooks installed: core.hooksPath -> %s\n' "${HOOKS_DIR}"
  printf 'Active hooks: pre-commit (secrets + YAML lint), pre-push (validation)\n'
  return "${EXIT_SUCCESS}"
}

main "$@"
