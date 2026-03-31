# Scaling Note - Running Reliably in the Cloud

To productionize this prototype, I would separate the system into four services: **data ingestion**, **policy execution**, **evaluation/analytics**, and **monitoring**.

## Reliability upgrades
- Run the policy on a scheduler with idempotent daily jobs.
- Store raw inputs, recommendations, and evaluation logs in durable cloud storage.
- Add retries with exponential backoff for upstream read failures.
- Validate schemas before execution so missing columns or malformed data fail fast.

## Observability
- Emit structured logs for every run: input file version, budget totals, channel scores, final allocation, and guardrail overrides.
- Track dashboards for conversion lift, CPA drift, error rate, and how often caps/floors are triggered.
- Alert when the agent produces abnormal allocations or receives stale data.

## Cost and safety caps
- Hard-cap daily spend and per-channel share in config.
- Add a manual approval path for unusually large shifts.
- Cache repeated computations and keep the policy lightweight so inference cost stays near zero.

## What I would improve next
- Replace the heuristic score with a contextual bandit or Bayesian budget model.
- Add attribution lag handling, uncertainty intervals, and experiment holdouts.
- Support API-based reads from ad platforms instead of CSV-only input.
