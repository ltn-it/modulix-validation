#!/usr/bin/env bash
# Admission adapter only. The managed dispatcher owns every container argument.
set -euo pipefail

fail_closed() { printf 'Error: %s\n' "$1" >&2; exit 1; }
case "${1:-}" in check|run) ;; *) fail_closed 'expected check or run' ;; esac
[ -n "${QUALITY_INCUS_CONFIG_DIR:-}" ] \
  || fail_closed 'approved Incus transport is unavailable; runtime activation remains deferred'
[ -d "$QUALITY_INCUS_CONFIG_DIR" ] && [ ! -L "$QUALITY_INCUS_CONFIG_DIR" ] \
  || fail_closed 'approved Incus transport must be a private regular directory'
# The workspace is the Supplementary source checkout. Use the centrally managed
# dispatcher shipped by the native SHA-pinned ModuLix action archive instead.
action_root="${QUALITY_ACTION_ROOT:?}"
[ -d "$action_root" ] && [ ! -L "$action_root" ] \
  || fail_closed 'native action root is unavailable'
archive_root="$(cd -- "$action_root/../../.." && pwd -P)"
wrapper="$archive_root/scripts/wunder-devtools-ee.sh"
[ -f "$wrapper" ] && [ ! -L "$wrapper" ] \
  || fail_closed 'managed Devtools dispatcher is unavailable'
grep -Fxq '# WUNDER_DEVTOOLS_QUALITY_CONTEXT: protected-incus-v1' "$wrapper" \
  || fail_closed 'managed Devtools dispatcher has no approved protected-incus-v1 contract'
if [ "$1" = check ]; then
  exec bash "$wrapper" --quality-incus-v1-check "${QUALITY_ACTION_ROOT:?}"
fi
exec bash "$wrapper" --quality-incus-v1 "${QUALITY_ACTION_ROOT:?}"
