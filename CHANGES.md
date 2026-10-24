# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan written as data before the issue is read; a validator with four checks; an executor that runs only the plan's steps; one checkpoint that may revise the plan; a second pass before the comment; detectors and a diff over traces; a progress file and a compaction
- **Removed:** the model's choice of the next tool, in the planned way
- **Constrained:** every tool call to a step of a validated plan; revisions to steps not yet done; the comment to drafts that pass the second pass

## Assignment 3
- **Added:** five redesigned tool definitions and examples; input/output boundary validation; actionable errors and bounded transient retries; draft-before-write execution; stable write keys, existence checks, timeout verification and escalation; per-attempt call records and fail-closed hooks; control switches and regression tests.
- **Removed:** generic tool names, vague descriptions and free-text filters; blind write retries in the normal configuration.
- **Constrained:** the plan to one PR immediately before one final comment; the comment to the prepared draft; writes to verified, bounded recovery with stable arguments and keys, with deliberate naive behavior only under control switches.

Part D: added provider token-difference measurements in `eval/price_surface.py`, tracker-based counts and surface pricing in `eval/measure_03.py`, pre-evaluation predictions, and focused measurement tests. Reviser requests now include the tool list required by the measurement design.
