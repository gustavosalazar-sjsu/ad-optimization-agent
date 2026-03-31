# Design Doc - Ad Optimization Agent

## Agent role
The agent acts as a **daily media budget allocator**. It reads recent channel performance, recommends the next day's budget split across Search, Social, and Display, and logs a short rationale for each move.

## Inputs
- CSV with: `date, channel, spend, impressions, clicks, conversions`
- Optional total daily budget (defaults to the next day's observed total in the backtest)
- Policy settings: trailing window, floor share, max daily change, exploration share

## Outputs
- Recommended budget by channel for each day
- Per-channel reason strings explaining the shift
- Evaluation log against an equal-split baseline
- Summary metrics and charts

## Policy logic
1. Aggregate the trailing 3 days of performance by channel.
2. Compute CTR, CVR, CPA, and conversions-per-dollar.
3. Score channels using:
   - 75% normalized conversions-per-dollar
   - 25% normalized CTR
4. Convert scores into a target budget split with a 10% exploration reserve.
5. Enforce guardrails before finalizing the budget.

## Guardrails
- **Budget stability:** cap per-channel day-over-day budget changes at +/-20%
- **Learning floor:** keep at least 20% of daily spend on every channel
- **Over-concentration control:** cap any single channel at 60% of daily spend
- **Logging:** every decision must include a human-readable reason string
- **Privacy:** no PII or user-level data is required; the prototype uses channel-level aggregates only
- **Brand tone:** the system should be neutral, factual, and avoid making unsafe or unverified business claims

## Evaluation metric
Primary metric: **total estimated conversions** over the backtest window.
Secondary metrics: **average estimated CPA** and qualitative review of decision logs.

The prototype compares the agent against an equal-split baseline on the same total daily budget.
