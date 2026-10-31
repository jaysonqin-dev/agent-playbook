# 2. The learning loop: turning corrections into rules

Most of what makes an agent good in daily use is not in the first version of its instructions. It comes from correcting it and keeping the correction.

## The loop

1. **Trigger: any correction.** The user rewrites a draft, says "that's wrong", or silently does it themselves. The last one counts too: if the user did not use the agent's draft and wrote their own, the diff between the two is the lesson.
2. **Triage against a quality bar.** Is it:
   - **general** enough to help in a future session,
   - **specific** enough to act on,
   - backed by a **concrete right-versus-wrong example**,
   - **not already covered** by an existing rule?
3. **Capture or skip.** If it passes, write the rule now, without waiting to be told to. If it is a one-off ("change this row's value"), do the work and write nothing. Logging every minor correction creates noise that hides the rules that matter.
4. **Disclose in one line.** Tell the user what was captured so they can veto or correct it.
5. **Retire.** Rules that no eval or real interaction ever needs get removed during consolidation.

## Capture or skip: examples

| Correction | Decision | Why |
|---|---|---|
| "Change this row's stage from P2 to P1." | Skip | One data fix, nothing to generalize. |
| The agent subtracted an already-netted quantity twice. | Capture | General: verify metric definitions against the source. Has a worked example. |
| The agent proposed a feature nobody asked for while offering options. | Capture | General: offer only what was requested; restate ambiguous phrases before building. |
| "Shorter, please." on one email. | Skip, unless it repeats | One data point. Three of them become a style rule. |
| A repeated edit pattern across several drafts. | Capture | The pattern is the lesson, not any single edit. |

## Two failure modes of the loop

- **Surface-level editing.** After two rounds where each fix only swaps a word and still gets rejected, stop editing and diagnose the structure (a run-on sentence, wrong order, wrong register). Repeated stuck edits are themselves the signal.
- **Over-capture.** A rule file that records everything is a rule file nobody, including the agent, can follow. The quality bar exists to keep it short.

## Measuring whether it works

Correction rate per week (the share of requests the user had to correct) is the number to watch, next to tool errors. The [monitoring report](05-deployment-and-monitoring.md) computes it. A falling rate is evidence the loop works; a spike right after an instruction change is evidence the change broke something, which is what the [evaluation set](03-evaluation.md) is for.
