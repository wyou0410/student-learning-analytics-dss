# Engineering evaluation

This evaluation concerns calculation contracts and a runnable synthetic prototype, not learning gains or prediction accuracy.

## Public-release scope

The original V2 workspace contained 38 tests, including two tests for the earlier dashboard. The public release removes that dashboard and those two interface tests, while retaining its shared SQL/calculation regression checks. The public test count is therefore 36.

On 2026-10-06, a fresh editable environment using Python 3.12.14 on Windows passed **36 tests in 82.50 seconds**. The headless demo completed with zero quarantined rows, the expected four-group counts and a 42-page PDF for 40 students. Windows is checked locally. Ubuntu is tested by the published GitHub Actions workflow; consult its live run rather than assuming it has passed.

## Hand-calculated cases

| Case | Inputs | Expected result |
|---|---|---|
| Both steady | Each domain 6 questions × 2/2, split across 2 tasks | 100% / 100%, group 11 |
| Algebra consolidation | Algebra 0/12, geometry 12/12, 2 tasks each | Group 01 |
| Geometry consolidation | Algebra 12/12, geometry 0/12, 2 tasks each | Group 10 |
| Both need support | Both domains 0/12, 2 tasks each | Group 00 |
| Ability independence | Change probe scores from 0/12 to 12/12, keep foundation scores fixed | Ability observation changes, group does not |
| Insufficient geometry | Algebra 6 questions, geometry 2 fully correct questions | Geometry remains limited; no forced four-group label |
| One-task evidence | 6 correct responses from just one task | Still limited |
| Composition shift | Easy/hard counts 6/18 versus 18/6, easy all correct and hard all zero | Fixed-stratum rate is 50% in both periods, not a false decline |
| Different composition group | Previous and current questions have different comparison groups | No comparable trend |
| Future changes | Change only responses submitted after the cutoff | Past profiles and selected evidence are identical |

The fixtures and assertions are visible in tests/test_teacher.py, tests/test_contracts.py and tests/test_extra_boundaries.py. Teacher UI tests use temporary databases rather than the packaged demonstration state.

## End-to-end behavior

The default synthetic generation produces 80 students, 10 knowledge points, 42 questions, 36 tasks, 2,880 assignments and 33,298 response records. At 2026-03-16 / 14 days, groups 11/01/10/00 contain 18/19/18/25 students. Those are deterministic demo outputs, not classification accuracy against real labels.

Checks cover quarantine and integrity constraints, earliest scored attempts, missing-value behavior, assigned denominators, comparable trends, cutoff leakage, snapshots, idempotent review updates, re-opened review state, five teacher pages and stale report-scope prevention.

PDF checks confirm Chinese text extraction and all 40 intended class students, with no students from another class and no developer payload. The curated 42-page example was rendered and visually inspected in the V2 workspace. Different fonts or report content should be checked again for layout.

## Still unverified

Question correctness and curriculum suitability need professional review; difficulty and the 70% threshold are not calibrated. There is no authentic classroom trial, measured usability study, intervention-effect estimate or model benchmark. The dataset generation parameters do not constitute educational ground truth.
