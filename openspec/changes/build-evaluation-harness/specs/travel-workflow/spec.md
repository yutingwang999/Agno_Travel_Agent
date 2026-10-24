## MODIFIED Requirements

### Requirement: Per-step trace record
Each executed step SHALL write one row to `trace_events` containing `session_id`, `step_name`, `status`, and `latency_ms`. The generate step SHALL also record `prompt_template_key` and `prompt_template_version` on success; the validate_output step SHALL also record `degraded_mode` and, when applicable, `error_type`. Every step that calls the LLM SHALL also record `input_tokens` and `output_tokens` summed over its LLM calls, or null when the provider reports no usage. A failure to write a trace row SHALL be logged and SHALL NOT fail the step.

#### Scenario: Trace rows for a run
- **WHEN** a high-confidence run completes
- **THEN** `trace_events` contains one row each for `intake`, `cag_match`, `retrieval_decision`, `generate`, and `validate_output` with the request's `session_id`

#### Scenario: Trace database unavailable
- **WHEN** inserting the trace row raises a database error
- **THEN** the error is logged and the step still returns its event

#### Scenario: Token usage recorded
- **WHEN** the generate step's LLM call reports 1,200 input tokens and 800 output tokens
- **THEN** the generate trace row has `input_tokens` = 1200 and `output_tokens` = 800

#### Scenario: Corrective retry tokens included
- **WHEN** validate_output makes one corrective LLM call
- **THEN** its trace row records that call's token usage
