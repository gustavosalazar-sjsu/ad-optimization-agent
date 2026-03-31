# Ad Optimization Agent

A minimal agent that reallocates daily budget across **Search, Social, and Display** to maximize conversions while preserving exploration and guardrails.

## Repo contents
- `ad_optimization_agent.py` - main script
- `mock_ad_data.csv` - 21 days of mock channel data
- `DESIGN_DOC.md` - one-page design summary
- `SCALING_NOTE.md` - cloud-readiness notes
- `outputs/` - successful run artifacts, logs, and charts
- `slides/` - 2-3 minute presentation deck

## How to run
```bash
pip install -r requirements.txt
python ad_optimization_agent.py --csv mock_ad_data.csv --output_dir outputs --generate_mock --days 21
```

If you already have the CSV, skip `--generate_mock`.

## What the script does
1. Reads daily channel performance from CSV.
2. Computes trailing 3-day CTR, CVR, and conversions-per-dollar.
3. Recommends the next budget split using a lightweight explore/exploit policy.
4. Applies guardrails:
   - max +/-20% per-channel day-over-day change
   - 20% minimum budget floor per channel
   - 60% maximum share per channel
5. Logs a reason string for every channel decision.
6. Evaluates the policy against an equal-split baseline.

## Assumptions
- Objective metric is **conversions**, with CPA used as a secondary efficiency check.
- Evaluation is an **offline estimate** using same-day observed efficiency plus a mild diminishing-returns penalty when budget moves far from observed spend.
- Mock data is intentionally simple and does not include attribution lag, auctions, or creative fatigue.

## Results snapshot
Successful run on the included 21-day dataset:
- **Estimated conversions (agent):** 2930.75
- **Estimated conversions (equal-split baseline):** 2610.26
- **Estimated conversion lift:** **+12.28%**
- **Average estimated CPA (agent):** **$5.51**
- **Average estimated CPA (baseline):** **$6.18**

See `outputs/successful_run.txt`, `outputs/evaluation_summary.json`, and the generated charts for the full snapshot.

## Submission note
You can upload this folder to GitHub and replace the placeholder repo URL in your final submission form.
