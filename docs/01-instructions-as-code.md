# 1. Instructions are code

An agent's instructions run on every turn. Treat them like a program: version them, review diffs, and test them.

## Structure that has worked for me

| Section | What goes in it |
|---|---|
| Mission | Who the agent serves and what "done" means. A few lines. |
| Execution policy | What it may do alone and what needs approval (see [tool design](04-tool-design.md)). |
| Working style | How it approaches a task: restate the goal, ask when ambiguous, check its own work before delivering. |
| Domain rules | Data access patterns, metric definitions, routing between sources. The longest section. |
| Output standards | Format and length, so answers can be compared run to run. |
| Learning loop | How corrections become rules (see [the learning loop](02-learning-loop.md)). |

A rule is only worth keeping if it has three parts: the rule in one bold sentence, the reason, and one concrete right-versus-wrong example. A rule without an example gets paraphrased differently on every turn.

## Put exact values in Instructions, not in a knowledge base

Knowledge retrieval is probabilistic: the agent decides whether to search at all, and the retrieved text can be truncated or paraphrased. Instructions are read in full, every turn. So anything that must be followed exactly belongs in Instructions: identifiers, connection details, the precise workaround for a known tool bug. Reserve the knowledge base for large reference material where an approximate answer is acceptable.

## Never encode a metric from a verbal description

A formula written from someone's description is unverified until it is checked against the source's own definition. See lesson 1 in [lessons](06-lessons.md): the rule I wrote would have subtracted reserved stock twice. When the definition cannot be checked, write "verify against the model definition before use" in the instructions instead of stating the formula as fact.

## Keep it healthy

- One real file, in git. Two copies in different folders mean two registrations of the same agent.
- Rules get longer over time. Consolidate periodically: merge duplicates, delete rules the evals no longer need, and look for contradictions.
- Every edit is a release. Run the [evaluation set](03-evaluation.md) before and after, and read the regressions before the pass rate.
- Keep personal or environment-specific details out of any instruction file that will be shared, even if the method was first built around them.

My own working agent has an instruction file of about 60 KB with roughly 130 rules, grown one correction at a time over about three months. That size is a cost: it is why consolidation and evals matter.
