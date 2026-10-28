## MODIFIED Requirements

### Requirement: LLM call
The step SHALL send the resolved prompt to the Gemini model named by `LLM_MODEL` (default `gemini-3.1-flash-lite`) and SHALL pass the response text through unmodified as `raw_llm_output`.

#### Scenario: Default model
- **WHEN** `LLM_MODEL` is unset
- **THEN** `gemini-3.1-flash-lite` is called
