# 4. Tool design

## One tool per fixed data source

If an agent can query several datasets, give each its own tool with the identifiers hard-coded, rather than one shared tool where the model fills in a dataset ID. Choosing among clearly named tools is something a model does reliably. Reproducing a 36-character identifier correctly on every call is not, and one wrong character fails silently as a "not found". Only the query text should be left for the model to write.

## Descriptions are contracts

The tool name and description are how the model decides what to call. Write them like an API contract: what the tool answers, what it does not, and an example question. A vague description is an unreviewed routing rule.

## Route between sources explicitly

When some questions belong to the data tools and others to documents, mail or chat, say which source answers which kind of question, and what to do with a mixed question (run the sources in parallel). Otherwise an HR question gets answered from a metrics dataset, confidently and wrongly.

## A channel limitation is not fixable with more tools

If an attachment is dropped on one chat surface but arrives on another with the same agent and model, the problem is how that client packages the message. Tools only help after the agent has received the message. Adding connectors will not fix it; route around it by using the surface that works, and report it as a platform issue.

## Writes need a different kind of care

Reading is cheap to get wrong. Writing is not.

- **Dry-run first.** Show the planned actions and what would change, then wait for approval.
- **Bind approval to the exact plan.** If the plan changes after approval, the approval is void.
- **Classify before you write.** Read the target's schema and decide per field what can be written safely (computed fields, validated lists, people fields). Do not discover the rules by trial and error on the live system.
- **Log and make it undoable.**

The [`agent-tool-safety`](https://github.com/qjl0629/agent-tool-safety) repository implements these as a small library with tests, against a mock spreadsheet API that reproduces the usual failure modes.
