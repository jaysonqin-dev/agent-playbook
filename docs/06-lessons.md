# 6. Lessons

Ten failures from building and running a team-facing analytics agent, each reduced to symptom, cause and the rule I kept. Details are generalized and all examples are synthetic; the underlying incidents were real.

### 1. A metric rule that would have counted a deduction twice
**Symptom.** Instructions said "sellable = available minus reserved". The live agent read the data model's glossary, which defines `available` as already net of reserved and quarantined units.
**Cause.** I wrote the formula from a verbal description and never checked the source's own definition.
**Rule.** Look for the glossary, measure definition or formula column before encoding any calculation. If it cannot be checked, label it "verify before use". The eval case `md1` in this repo reproduces the failure.

### 2. Identifiers retyped by the model
**Symptom.** Intermittent "not found" from a data tool.
**Cause.** One shared tool with a model-filled dataset ID. One wrong character in a 36-character ID fails silently.
**Rule.** One tool per fixed source, identifiers hard-coded, only the query text model-written.

### 3. Fixing a client bug with more connectors
**Symptom.** Images reached the agent on one chat surface and not on another.
**Cause.** That client does not pass attachments to custom agents. Tools run after the message is received, so they cannot change what was sent.
**Rule.** If the issue is isolated to one surface, treat it as a platform bug and route around it.

### 4. Scope inferred from a name
**Symptom.** Instructions rewritten twice.
**Cause.** I took the audience from an existing label instead of asking who would use the agent and for what range of tasks.
**Rule.** Confirm the audience before drafting.

### 5. An agent that vanished from the picker
**Symptom.** A custom agent stopped appearing after a restart.
**Cause (found by evidence, not guessing).** A stale sync, and an unquoted colon in a YAML description that strict parsers reject.
**Rule.** Read the docs for supported folders, check the sync cache, validate the front matter with a real parser, use a lowercase-hyphen filename, keep one real file.

### 6. The same agent listed twice
**Symptom.** Two identical entries in the picker.
**Cause.** I had created a symlink in a second agents folder to "make sure it was found". The tool derives identity from the filename, so both copies registered.
**Rule.** One real file, nowhere else.

### 7. Debugging writes by inserting real rows
**Symptom.** A write failed with a generic "value not supported" error; bisecting by posting half-payloads left malformed rows behind in the production sheet.
**Rule.** Classify columns from metadata before writing. If a generic error still occurs, create one disposable row and bisect with updates to that single row, then delete it. Afterwards, audit for orphaned rows. This is implemented in [`agent-tool-safety`](https://github.com/qjl0629/agent-tool-safety).

### 8. Stating platform behavior I had not verified
**Symptom.** I told a user a setting required starting a new chat. It did not.
**Rule.** If I am inferring how a tool works, say so, or check the documentation first.

### 9. An edit and its test in the same batch
**Symptom.** A mutation check "passed" because the test ran before the edit landed.
**Cause.** Independent tool calls issued in one block can run in parallel.
**Rule.** Edit first, then test, as separate steps.

### 10. Positioning before surveying the field
**Symptom.** A first search suggested similar tools were small. A later search for names found a much larger competitor with overlapping features.
**Rule.** Search with several query variants, including other languages, and read the top hits before choosing a name or a claim; then say plainly where the product differs.
