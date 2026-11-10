# Actual producer matrix fixtures

`protected-main.json` contains the complete supported Heavy and Application
matrices from Supplementary Main
`7311d20519faf576a7627bea66516c8c8c505ca2`, path
`docs/testing/generated/role-coverage-matrix.json` → `profiles`.

`pending-physical-vm.json` contains the same complete profiles from candidate
`fba90cc476779264567bf96806d19a0936c91e6e`. It is pending publication, not claimed
as protected Main. `scripts/validate-role-coverage.py:build_matrix` produces both
shapes. Generic container compatibility is not G06 VM acceptance; both pending
G06 rows and Root-prepared cells must remain VMs.
