# Analysis contracts and system design

## Source checkout and offline pipeline

The supported execution mode is a repository checkout with an editable Python installation. SQL, schemas and configuration are read relative to that checkout; the project is not advertised as a standalone wheel or a hosted service.

The generator writes CSVs plus a SHA-256 manifest. Ingestion checks synthetic-only flags, columns, numeric types, timestamp precision, foreign keys, score bounds and assignment eligibility. Invalid records are quarantined with a reason. Question tags have their own manifest validation and database constraints. New import paths are required: existing databases are never silently replaced.

The teacher UI is a presentation layer over the SQLite/SQL calculation engine. Shared lower-level rule modules and fixtures remain in the public source because they exercise established contracts; the earlier dashboard and its interface-specific tests are not part of this release.

## Response selection and denominators

Analysis dates normalize to UTC end-of-day; timestamps require a timezone and whole-second precision. Queries filter eligible assignments, task availability and response submission by the cutoff. Among valid scored responses for a student/task/question, ordering is attempt number, submission timestamp, then response ID. A later retry does not replace the first valid scored response.

An unscored response remains absent from score aggregation. Scores are aggregated as sum(score) / sum(max_score); empty denominators return None. Task completion is submitted eligible due tasks / assigned eligible due tasks. This is a completion observation, not proof of mastery or full task completion.

The schema has no separate grade-publication timestamp. Cutoff safety is tested for immutable response records and their submission timestamps; retrospectively changing a past response's score changes the historical input. This prototype cannot reconstruct when a later grading update became visible in a real school.

## Stage-specific labels and groups

The teacher rule configuration is versioned in configs/teacher.yaml. For a domain or knowledge point, at least five scored responses across two distinct tasks are required. A score ratio of at least 0.70 produces a steady label; below that produces a consolidation label. Insufficient evidence remains explicitly limited.

Only foundation questions determine algebra and geometry groups. Bits are algebra then geometry:

| Code | Observation |
|---|---|
| 11 | Both domains steady |
| 01 | Algebra needs consolidation |
| 10 | Geometry needs consolidation |
| 00 | Both domains need support |
| pending | At least one domain needs more observation |

Knowledge-point gaps are retained even when a domain's aggregate is steady. Ability probes separately observe computation, reasoning and application; they do not alter the group. Missing process, hint and independence fields are not invented or used to infer broad ability.

The rule thresholds and teaching-action templates are demonstration settings, not validated educational cutoffs.

## Comparable trends

Windows are 7, 14 or 28 days, with adjacent windows of equal length. Trend strata must share knowledge point, difficulty and the fixed question-composition group. Each shared stratum needs five observations and two tasks in both current and preceding windows.

Shared strata receive fixed equal weights in each window, so changed easy/hard question counts cannot alone create a trend. A third window is included only when the same strata are sufficient there. The demonstration change threshold is 0.15; otherwise the wording indicates a small change or insufficient comparable evidence.

Repeated question compositions support engineering comparisons but would introduce potential memory effects in actual teaching. Difficulty labels are not psychometrically calibrated.

## Provenance, teacher judgment and PDF

The result snapshot retains selected response rows, question tags, task assignments, rule configuration and data/code/config hashes. Domain and ability summaries include the supporting response IDs. These engineering details stay outside the teacher pages.

Teacher reviews are keyed by run/student/scope/key. Confirmation or adjustment requires a selected action; decisions, reasons and follow-up times use presets. Updates are idempotent. A changed snapshot does not inherit an earlier decision.

Reports separate teacher-confirmed actions, suggestions awaiting confirmation and deferred matters. A partial domain review does not masquerade as a completed overall review. Changing report scope invalidates the previously generated download.

Chinese PDFs use an available Chinese font. Windows defaults to SimHei; Linux checks DroidSansFallbackFull.ttf and otherwise uses a built-in CJK fallback. LEARNING_SUPPORT_FONT can point to a suitable TTF. Cross-platform tests check extraction and coverage; layout should be visually checked when changing fonts.
