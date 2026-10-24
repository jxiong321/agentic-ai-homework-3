# Assignment 3 predictions (before evaluation)

These predictions use development tests only. Neither evaluation arm has run.
The model stays gemini-3.5-flash-lite, with critique off and notes off in both arms.

| Prediction across 12 runs per arm | Harness | Control |
|---|---:|---:|
| Extra duplicate comments (sum of comments beyond the first in each run) | 0 | 6 |
| Runs with duplicate comments | 0 | 5 |
| Extra duplicate PRs | 0 | 0 |

- Harness comments: stable keys and verification should recover committed timeouts without posting again.
- Control comments: fresh keys and blind retries should create duplicates after committed timeouts; six extra comments across five runs is an estimate, not a guarantee about the fault schedule.
- PRs in both arms: checking the existing open PR by run and branch should prevent duplicate PRs even in the control.
- Most misused tool: codebase_search, because choosing useful search terms and the appropriate path scope still requires interpreting the issue, even with valid arguments.
- Remaining reliability risk: the development model sometimes returns incomplete args_json in submit_plan; rejected plans can leave no comment in either arm, despite correct write protection. This is a planner-format failure, not evidence that a duplicate was prevented.

I will report every measured run, including safe escalations and incorrect triage, and explain deviations without replacing unfavorable runs.
