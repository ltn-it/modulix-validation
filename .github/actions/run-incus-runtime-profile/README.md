# Physical execution and final quality

Physical execution and final quality are separate native jobs. The execution
job uses `run-profile`, uploads its sanitized preliminary package, and calls
`record-upload` with that upload's native artifact ID and digest. The installed
Root client obtains the actual size; Root independently authenticates the
original invocation, artifact and execution job. The execution job must end
successfully before Root can grant final success.

The Root-sealed engine environment requires
`QUALITY_FAILURE_CUSTODY=retain-failed-v1`. Its exact engine and custody policy
digests are bound by the existing admission signature. It is not a workflow
input, and private command files cannot replace it. All physical destruction
belongs to Root. Thin lifecycle evidence records `destroy_exit_code: null`
and `root_finalization: pending`; preliminary evidence is never release proof.
Actual test, capture, packaging and cancellation outcomes remain unchanged.
The local `result.json` always has `success: false` while pending and separately
records `execution_success`. Missing or unknown custody directives fail closed.

The fresh `Final quality / <profile> / <scenario> / <target>` job calls only
`observe-profile`. It gets no new execution lease. Root verifies the original
execution job's actual terminal success and native upload, performs and reads
back owned deletion, and closes the original ledger before returning a signed
`final-quality-receipt.json`. Failed, cancelled or expired execution is retained
under the archived four-hour custody policy; no observer turns it into ordinary
quality success. Independent Root timers operate after the execution job ends.

The observer publishes exactly that receipt as
`root-final-quality-<run>-<profile>-<scenario>-<target>`. Source aggregation must
verify the receipt signature against an independently pinned Root public key,
the exact invocation/cell, terminal native execution, original preliminary
artifact ID/digest/size, and verified closed cleanup. Neither an observer check
alone nor self-reported receipt key establishes final quality. Failure to
publish an observer receipt does not change the already recorded execution
outcome or grant another lease.

This contract does not establish deployment, real-host acceptance or successful
four-hour watchdog/mail delivery. Those require the actual installed Root ABI,
protected native execution and later operating receipts.

The four installed-client execution and observer preflights require
`check --require-capability initial-auth-idle-v1` and the exact canonical local
record: authentication idle allowance 60 seconds, frame bound 5 seconds. An older
client or another response fails before requesting work. This is a local client
interface check, not evidence that Root authentication or its collector is healthy.
The accepted package, actual host readiness and full authentication budget remain
independent requirements. Both failed original Main runs remain evidence; a new
functional Source transition requires an exact Root-bound continuation, never an
attempt-two rerun or a deadline reset.
