## ADDED Requirements

### Requirement: Token usage in trace rows
Every step that calls the LLM SHALL record, in its trace row, `input_tokens` and `output_tokens` summed over its LLM calls, or null when the provider reports no usage.

#### Scenario: Token usage recorded
- **WHEN** the generate step's LLM call reports 1,200 input tokens and 800 output tokens
- **THEN** the generate trace row has `input_tokens` = 1200 and `output_tokens` = 800

#### Scenario: Corrective retry tokens included
- **WHEN** validate_output makes one corrective LLM call
- **THEN** its trace row records that call's token usage
