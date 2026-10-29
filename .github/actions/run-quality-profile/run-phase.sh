#!/usr/bin/env bash
set -uo pipefail

# Keep each Molecule phase below the enclosing job limit so capture and
# destruction still run when the test process hangs.
if [ "$#" -ne 2 ] || [[ ! "$2" =~ ^[1-9][0-9]{0,3}$ ]] || [ "$2" -gt 5400 ]; then
  echo "Usage: run-phase.sh {test|cleanup|destroy} timeout-seconds (1..5400)" >&2
  exit 2
fi

phase="$1"
duration_seconds="$2"
: "${QUALITY_SCENARIO:?QUALITY_SCENARIO is required}"
: "${QUALITY_LOG_PATH:?QUALITY_LOG_PATH is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

case "$phase" in
  test)
    command=(molecule test -s "$QUALITY_SCENARIO" --destroy never)
    # The log is initialized here, including for a retry in the same workspace.
    log_mode=()
    ;;
  cleanup|destroy)
    command=(molecule "$phase" -s "$QUALITY_SCENARIO")
    log_mode=(-a)
    ;;
  *)
    echo "Unsupported Molecule phase: $phase" >&2
    exit 2
    ;;
esac

set +e
timeout --signal=TERM --kill-after=30s "${duration_seconds}s" \
  "${command[@]}" 2>&1 | tee "${log_mode[@]}" "$QUALITY_LOG_PATH"
phase_rc="${PIPESTATUS[0]}"
set -e
printf 'exit_code=%s\n' "$phase_rc" >> "$GITHUB_OUTPUT"
exit 0
