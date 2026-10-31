## MODIFIED Requirements

### Requirement: Constraint satisfaction metric
The harness SHALL report, for planned itineraries, the share that satisfy each constraint: the number of days equals the requested trip length; the total cost, interpreted as AUD per person excluding accommodation, does not exceed the request's daily budget ceiling multiplied by the trip length; and every attraction is in the requested destination as decided by the judge model.

#### Scenario: Budget exceeded
- **WHEN** a 3-day `budget` request without `max_daily_budget_aud` produces a per-person total above 3 times the configured per-person per-day upper bound for `budget`
- **THEN** that itinerary fails the budget constraint

#### Scenario: Amount in the request
- **WHEN** a 2-day `luxury` entry has `form.max_daily_budget_aud` = 1500 and its itinerary totals 5,000
- **THEN** that itinerary fails the budget constraint

### Requirement: Uncapped budget levels
For a request without a daily budget ceiling (a level with no configured upper bound and no `max_daily_budget_aud`), the budget constraint SHALL be reported as not applicable for that entry and SHALL be left out of the budget constraint share.

#### Scenario: Level without a cap
- **WHEN** a `luxury` request without `max_daily_budget_aud` produces an itinerary
- **THEN** its budget constraint is reported as N/A and the entry is not counted in the budget constraint share

## ADDED Requirements

### Requirement: Budget amount in the dataset
An entry's `form` MAY contain `max_daily_budget_aud`, an integer of at least 1. The harness SHALL send it with the request; a system without the field ignores it, and its budget constraint is still computed with the amount, as the user asked for it. The dataset SHALL include entries with an amount for each budget level, among them a `luxury` entry and an entry whose amount is above its level's default.

#### Scenario: Amount sent with the request
- **WHEN** an entry with `form.max_daily_budget_aud` is evaluated
- **THEN** the request body contains `max_daily_budget_aud` with that value
