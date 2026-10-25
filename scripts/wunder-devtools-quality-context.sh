#!/usr/bin/env bash
# Managed by lightning-it/shared-assets-lit.
# Managed companion of wunder-devtools-ee.sh; never invoke as a generic launcher.
set -euo pipefail
umask 077
fail() { echo "Error: protected-incus-v1: $*" >&2; exit 1; }
[[ $# == 3 ]] || fail "expected fixed image, API mode and native action root"
image=$1 mode=$2 action=$3
[[ $image =~ ^quay.io/l-it/ee-wunder-devtools-ubi9:v[0-9.]+@sha256:[0-9a-f]{64}$ ]] || fail "invalid managed image"
[[ $mode == --quality-incus-v1 || $mode == --quality-incus-v1-check ]] || fail "unsupported API"
[[ $(uname -s) == Linux ]] || fail "protected Linux runner required"
uid=$(id -u) gid=$(id -g)
[[ $uid != 0 ]] || fail "non-root runner required"
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_EVENT_NAME:-} == workflow_dispatch &&
   ${GITHUB_REPOSITORY:-} == ltn-it/modulix-validation && ${GITHUB_REPOSITORY_ID:-} == 1269461997 &&
   ${GITHUB_REF:-} == refs/heads/main && ${GITHUB_REF_PROTECTED:-} == true &&
   ${GITHUB_ACTOR:-} == 'lightning-it-release-automation[bot]' && ${GITHUB_ACTOR_ID:-} == 307565056 &&
   ${GITHUB_TRIGGERING_ACTOR:-} == "$GITHUB_ACTOR" && ${GITHUB_RUN_ATTEMPT:-} == 1 ]] || fail "unsupported protected receiver identity"
[[ ${GITHUB_RUN_ID:-} =~ ^[1-9][0-9]*$ && ${GITHUB_SHA:-} =~ ^[0-9a-f]{40}$ &&
   ${QUALITY_CONTROLLER_SHA:-} == "$GITHUB_SHA" && ${GITHUB_JOB:-} =~ ^[A-Za-z0-9_-]+$ ]] || fail "invalid run identity"
[[ ${QUALITY_ACTION_REPOSITORY:-} == ltn-it/modulix-validation &&
   ${QUALITY_ACTION_REF:-} =~ ^[0-9a-f]{40}$ && ${QUALITY_ACTION_ROOT:-} == "$action" ]] || fail "invalid native action context"
[[ ${WUNDER_DEVTOOLS_WORKSPACE_MODE:-ro} == ro && ${WUNDER_DEVTOOLS_NETWORK:-none} == none &&
   ${WUNDER_DEVTOOLS_PRIVILEGED:-0} == 0 && ${WUNDER_DEVTOOLS_DOCKER_SOCKET:-disabled} == disabled &&
   ${WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT:-disabled} == disabled && -z ${WUNDER_DEVTOOLS_CAP_ADD:-} &&
   ${WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH:-disabled} == disabled && -z ${CONTAINER_HOME:-} ]] || fail "incompatible sandbox override"

# Structural admission uses shell and platform file metadata only. Semantic
# YAML/TLS validation happens offline in the pinned container below.
safe_path() {
  local path=$1 parent part current=/
  [[ $path == /* && $path != / && $path != *[,:$'\n\r']* ]] || fail "unsafe host path"
  IFS=/ read -r -a parts <<< "$path"
  for part in "${parts[@]}"; do
    [[ -n $part ]] || continue
    [[ $part != . && $part != .. ]] || fail "noncanonical path"
    current="${current%/}/$part"
    [[ ! -L $current ]] || fail "symlink path"
  done
  parent=$(dirname -- "$path")
  [[ -d $parent && $(cd -- "$parent" && pwd -P)/$(basename -- "$path") == "$path" ]] || fail "nonphysical path"
}
owned_file() {
  safe_path "$1"
  [[ -f $1 && $(stat -c %u -- "$1") == "$uid" && $(stat -c %h -- "$1") == 1 ]] || fail "regular owned file required"
}
private_tree() {
  local root=$1 item
  safe_path "$root"
  [[ -d $root ]] || fail "private context missing"
  find "$root" -print0 | while IFS= read -r -d '' item; do
    [[ ! -L $item && $(stat -c %u -- "$item") == "$uid" ]] || fail "foreign context ownership"
    if [[ -d $item ]]; then
      [[ $(stat -c %a -- "$item") == 700 ]] || fail "private directory mode required"
    else
      owned_file "$item"
      [[ $(stat -c %a -- "$item") == 600 && $(stat -c %s -- "$item") -le 65536 ]] || fail "private bounded file required"
    fi
  done || fail "private context traversal failed"
}
safe_path "${RUNNER_WORKSPACE:-}"; safe_path "${RUNNER_TEMP:-}"
[[ -d $RUNNER_WORKSPACE && -d $RUNNER_TEMP ]] || fail "runner roots missing"
source=${GITHUB_WORKSPACE:-}
safe_path "$source"
[[ -d $source && $source == "$RUNNER_WORKSPACE/"* && $(pwd -P) == "$source" ]] || fail "source workspace containment"
expected_action="$(dirname -- "$RUNNER_WORKSPACE")/_actions/ltn-it/modulix-validation/$QUALITY_ACTION_REF/.github/actions/run-quality-profile"
[[ $action == "$expected_action" ]] || fail "native action path containment"
safe_path "$action"
for name in action.yml run-devtools.sh run-cell.py run-phase.sh profile-steps.yml; do owned_file "$action/$name"; done
action_members=$(find "$action" -mindepth 1 -maxdepth 1 | wc -l) || fail "action traversal failed"
[[ $action_members == 5 ]] || fail "unexpected action member"
context="$RUNNER_TEMP/mlx90-incus/$GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT"
[[ ${QUALITY_INCUS_CONFIG_DIR:-} == "$context" ]] || fail "run-bound private context required"
private_tree "$context"
context_files=$(find "$context" -type f | wc -l) || fail "context file traversal failed"
context_directories=$(find "$context" -type d | wc -l) || fail "context directory traversal failed"
[[ $context_files == 5 && $context_directories == 2 ]] || fail "unexpected context member"
for name in binding.json config.yml client.crt client.key servercerts/quality.crt; do owned_file "$context/$name"; done
output=${GITHUB_OUTPUT:-}
[[ $output == "$RUNNER_TEMP/_runner_file_commands/"* ]] || fail "output outside runner command directory"
owned_file "$output"

input_names=(PROFILE SCENARIO TARGET TARGET_DISPOSITION ROLES IMAGE INSTANCE_TYPE CANDIDATE_ARTIFACT SOURCE_SHA JUNIT_REQUIRED ALLURE_REQUIRED CPU_LIMIT MEMORY_LIMIT DISK_LIMIT)
for name in "${input_names[@]}"; do
  key="QUALITY_INPUT_$name" value=${!key:-}
  [[ -n $value && ${#value} -le 512 && $value != *[$'\n\r']* ]] || fail "invalid $key"
done
[[ $QUALITY_INPUT_PROFILE == heavy || $QUALITY_INPUT_PROFILE == application_acceptance ]] || fail "unsupported profile"
for value in "$QUALITY_INPUT_SCENARIO" "$QUALITY_INPUT_TARGET"; do
  [[ $value =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || fail "invalid scenario or target"
done
[[ $QUALITY_INPUT_TARGET_DISPOSITION == supported || $QUALITY_INPUT_TARGET_DISPOSITION == candidate ]] || fail "invalid disposition"
[[ $QUALITY_INPUT_SOURCE_SHA =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ && $QUALITY_INPUT_CANDIDATE_ARTIFACT =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$ &&
   $QUALITY_INPUT_ROLES =~ ^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$ && $QUALITY_INPUT_IMAGE =~ ^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$ &&
   $QUALITY_INPUT_INSTANCE_TYPE =~ ^(container|vm)$ &&
   $QUALITY_INPUT_JUNIT_REQUIRED =~ ^(true|false)$ && $QUALITY_INPUT_ALLURE_REQUIRED =~ ^(true|false)$ &&
   $QUALITY_INPUT_CPU_LIMIT =~ ^[1-9][0-9]{0,2}$ && $QUALITY_INPUT_MEMORY_LIMIT =~ ^[1-9][0-9]*(KiB|MiB|GiB|TiB)$ &&
   $QUALITY_INPUT_DISK_LIMIT =~ ^[1-9][0-9]*(MiB|GiB|TiB)$ ]] || fail "invalid typed profile input"
candidate="$RUNNER_TEMP/supplementary-candidate/$GITHUB_REPOSITORY_ID/$GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT/$GITHUB_JOB/$GITHUB_SHA"
if [[ $mode == --quality-incus-v1 ]]; then
  safe_path "$candidate"
  [[ -d $candidate ]] || fail "candidate missing"
  find "$candidate" -print0 | while IFS= read -r -d '' item; do
    [[ -d $item && ! -L $item && $(stat -c %u -- "$item") == "$uid" ]] || owned_file "$item"
  done || fail "candidate traversal failed"
fi
engine=${WUNDER_CONTAINER_ENGINE:-docker}
[[ $engine == docker || $engine == podman ]] || fail "unsupported engine"
engine=$(command -v "$engine") || fail "container engine missing"
[[ -z ${DOCKER_HOST:-} || ${DOCKER_HOST:-} == unix:///* ]] || fail "local engine endpoint required"

# Nothing is mounted or contacted before all structural admission above.
engine_home=$(mktemp -d "$RUNNER_TEMP/quality-engine.XXXXXXXX")
trap 'rm -rf -- "$engine_home"' EXIT
engine_env=(env -i "PATH=$PATH" "HOME=$engine_home")
[[ -z ${DOCKER_HOST:-} ]] || engine_env+=("DOCKER_HOST=$DOCKER_HOST")
if [[ ${WUNDER_CONTAINER_ENGINE:-docker} == podman ]]; then
  rootless=$("${engine_env[@]}" "$engine" info --format '{{.Host.Security.Rootless}}') || fail "Podman identity unavailable"
  [[ $rootless == false ]] || fail "protected-incus-v1 does not admit rootless Podman"
fi
base=(run --rm --read-only --cap-drop ALL --security-opt no-new-privileges=true --pids-limit 512 --user "$uid:$gid"
  --tmpfs '/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777'
  --tmpfs "/tmp/wunder:rw,exec,nosuid,nodev,size=1g,mode=1777,uid=$uid,gid=$gid"
  --env HOME=/tmp/wunder --env TMPDIR=/tmp/wunder --mount "type=bind,source=$context,destination=/incus,readonly")
[[ ${WUNDER_CONTAINER_ENGINE:-docker} != podman ]] || base+=(--read-only-tmpfs=false)
identity_env=()
for key in GITHUB_REPOSITORY GITHUB_RUN_ID GITHUB_RUN_ATTEMPT; do identity_env+=(--env "$key=${!key}"); done
preflight=$(cat <<'PY'
import datetime, json, os, pathlib, re, shutil, ssl, urllib.parse
import yaml
for command in ('incus', 'molecule', 'ansible', 'ansible-galaxy', 'python3', 'openssl', 'timeout', 'tar'):
    if not shutil.which(command):
        raise SystemExit('required pinned tool unavailable: ' + command)
root = pathlib.Path('/incus')
binding = json.loads((root / 'binding.json').read_text())
assert set(binding) == {'schema','repository','run_id','run_attempt','server','project','expires_at'}
assert type(binding['schema']) is int and binding['schema'] == 1
for key in ('repository','run_id','run_attempt'):
    assert binding[key] == os.environ['GITHUB_' + key.upper()]
expiry = datetime.datetime.fromisoformat(binding['expires_at'].replace('Z','+00:00'))
remaining = (expiry - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
assert 0 < remaining <= 5400
url = urllib.parse.urlsplit(binding['server'])
assert url.scheme == 'https' and url.hostname and not url.username and not url.password
assert url.path in ('','/') and not url.query and not url.fragment
assert isinstance(binding['project'], str) and re.fullmatch(r'[a-z][a-z0-9-]{0,62}', binding['project'])
config = yaml.safe_load((root/'config.yml').read_text())
assert set(config) == {'default-remote','remotes'} and config['default-remote'] == 'quality'
assert set(config['remotes']) == {'quality'}
remote = config['remotes']['quality']
assert set(remote) == {'addr','auth_type','project','protocol','public'}
assert remote['public'] is False
assert remote == {'addr':binding['server'], 'auth_type':'tls', 'project':binding['project'], 'protocol':'incus', 'public':False}
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
tls.load_cert_chain(str(root/'client.crt'), str(root/'client.key'))
tls.load_verify_locations(cafile=str(root/'servercerts/quality.crt'))
print('PROTECTED_INCUS_PREFLIGHT=1')
PY
)
"${engine_env[@]}" "$engine" "${base[@]}" --network none --env QUALITY_CONTEXT_PHASE=preflight "${identity_env[@]}" "$image" python3 -c "$preflight"
[[ $mode == --quality-incus-v1 ]] || exit 0
cell=$(mktemp -d "$RUNNER_TEMP/quality-cell.XXXXXXXX")
runtime_env=(--env QUALITY_CONTEXT_PHASE=runtime --env "QUALITY_DEVTOOLS_IMAGE=$image"
  --env "QUALITY_HOST_UID=$uid" --env "QUALITY_EFFECTIVE_UID=$uid" --env "QUALITY_EFFECTIVE_GID=$gid"
  --env INCUS_CONF=/incus --env RUNNER_TEMP=/quality/tmp --env GITHUB_WORKSPACE=/workspace
  --env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory --env GIT_CONFIG_VALUE_0=/workspace)
for key in "${input_names[@]/#/QUALITY_INPUT_}" GITHUB_REPOSITORY GITHUB_REPOSITORY_ID GITHUB_RUN_ID GITHUB_RUN_ATTEMPT GITHUB_JOB GITHUB_SHA GITHUB_WORKFLOW; do
  runtime_env+=(--env "$key=${!key:-}")
done
status=0
"${engine_env[@]}" "$engine" "${base[@]}" --network bridge --workdir /workspace \
  --mount "type=bind,source=$source,destination=/workspace,readonly" \
  --mount "type=bind,source=$candidate,destination=/candidate,readonly" \
  --mount "type=bind,source=$action,destination=/controller,readonly" \
  --mount "type=bind,source=$cell,destination=/quality" \
  "${runtime_env[@]}" "$image" python3 /controller/run-cell.py || status=$?
result="$cell/control/result.json"
owned_file "$result"
[[ $(stat -c %s -- "$result") -le 4096 && $(stat -c %a -- "$result") == 600 ]] || fail "invalid result file"
prefix=quality-result
[[ $QUALITY_INPUT_TARGET_DISPOSITION != candidate ]] || prefix='candidate-quality-result'
artifact="$prefix-$QUALITY_INPUT_SCENARIO-$QUALITY_INPUT_TARGET-$QUALITY_INPUT_SOURCE_SHA-attempt-$GITHUB_RUN_ATTEMPT"
expected_true="{\"package_directory\": \"/quality/package\", \"result_artifact\": \"$artifact\", \"schema\": 1, \"success\": true}"
expected_false="{\"package_directory\": \"/quality/package\", \"result_artifact\": \"$artifact\", \"schema\": 1, \"success\": false}"
# Match the driver's exact bytes, including its single terminating newline.
# Shell command substitution would discard NULs and trailing newlines.
if printf '%s\n' "$expected_true" | cmp -s -- "$result" -; then
  result_success=true
elif printf '%s\n' "$expected_false" | cmp -s -- "$result" -; then
  result_success=false
else
  fail "unrecognized result schema"
fi
safe_path "$cell/package"
[[ -d $cell/package ]] || fail "package missing"
find "$cell/package" -print0 | while IFS= read -r -d '' item; do
  [[ -d $item && ! -L $item ]] || owned_file "$item"
done || fail "package traversal failed"
printf 'package-directory=%s\nresult-artifact=%s\n' "$cell/package" "$artifact" >> "$output"
[[ $result_success == true && $status == 0 ]] || exit 1
