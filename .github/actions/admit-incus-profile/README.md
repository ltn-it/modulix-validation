# Protected Incus admission compiler

This immutable action owns hosted caller admission and the scheduling matrix
schema. It runs only its own `admission.py` in the digest-pinned Devtools image,
read-only, offline, non-root, without candidate checkout, credentials or a
service socket. Validation completes before any output is emitted.

The consumer must pin this action's real commit and use its canonical
`matrix-json` output for `strategy.matrix`; the raw input is never scheduled.
All outer/cell keys and every scalar, boolean, role, image selector and runner
list are checked. JSON duplicates/nonfinite values, unknown axes/fields and
duplicate scenario/target cells are refused. Input and canonical output are
bounded at 64 KiB, and a matrix has at most 256 cells, matching the
[GitHub matrix ceiling](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstrategymatrix).

The closed cell fields, identifier/role/image patterns and two runner label sets
follow Supplementary's `build_matrix` and registry schema. Only supported,
release-required rows enter the protected Main route. Candidate rows need a
separate contract. Resource limits stay at the commissioned 4 CPU/12 GiB/24 GiB.

Both registry-supported `container` and `vm` types are typed compatibility
inputs. Compatibility with an older protected Main container row does not prove
G06 VM acceptance: G06's pending physical profile rows and both Root-prepared
cells must remain VMs. The installed runtime action and its independent native
identity, ownership, expiry and lifecycle checks are unchanged.

The hosted check accepts two complete GitHub caller identities. The existing
MLX90 Main dispatch uses the release App and an `mlx90-candidate-<request-id>`
artifact. The direct Supplementary route uses a protected Main push through
`collection-ci.yml` in repository `1103407173`, attempt one, with `litroc`
(`76040632`) or `litdeg` (`247824904`) as the User actor and the same triggering
login. Its source SHA equals the GitHub caller SHA, and its artifact is exactly
`collection-candidate-<source-sha>`. Both routes use the same matrix compiler
and fixed limits. Mixed caller fields and a caller-supplied mode grant no route.

The additional context comes from GitHub expressions in the immutable action,
not from action inputs. Hosted compilation binds the workflow path. The
installed Root runtime independently verifies the actual run and workflow ID
(`214182490` for Supplementary), both native actor identities, OIDC claims,
Runner01 identity, and the private policy before admitting a cell.

The compiler also derives `worker-group` from that fully validated caller:
the original Validation domain retains `lit-pis-prd-isolated`, while direct
Supplementary uses only `lit-pis-prd-supplementary-isolated`. A matrix label,
environment variable or workflow input cannot choose a different group.
