import argparse
import json
from pathlib import Path
import math
import textwrap

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

CHANNELS = ["Search", "Social", "Display"]
SEED = 42


def generate_mock_data(output_csv: str, days: int = 21, seed: int = SEED):
    rng = np.random.default_rng(seed)
    start_date = pd.Timestamp("2026-02-01")

    # Latent channel characteristics for mock generation.
    channel_params = {
        "Search": {
            "cpm": 17.5,
            "ctr": 0.030,
            "cvr": 0.120,
            "spend_base": 320,
            "trend": 0.0004,
        },
        "Social": {
            "cpm": 11.0,
            "ctr": 0.018,
            "cvr": 0.080,
            "spend_base": 300,
            "trend": 0.0008,
        },
        "Display": {
            "cpm": 7.0,
            "ctr": 0.010,
            "cvr": 0.045,
            "spend_base": 280,
            "trend": -0.0001,
        },
    }

    rows = []
    for day in range(days):
        current_date = start_date + pd.Timedelta(days=day)
        weekend_factor = 0.92 if current_date.dayofweek >= 5 else 1.0
        seasonality = 1.0 + 0.03 * math.sin(day / 3.0)
        for channel in CHANNELS:
            p = channel_params[channel]
            spend_noise = rng.normal(1.0, 0.07)
            spend = max(180.0, p["spend_base"] * seasonality * weekend_factor * spend_noise)

            cpm = p["cpm"] * rng.normal(1.0, 0.04)
            ctr = max(0.003, (p["ctr"] + p["trend"] * day) * rng.normal(1.0, 0.07))
            cvr = max(0.01, (p["cvr"] + 0.6 * p["trend"] * day) * rng.normal(1.0, 0.08))

            impressions = int(max(1000, spend / cpm * 1000 * rng.normal(1.0, 0.03)))
            clicks = int(max(1, impressions * ctr * rng.normal(1.0, 0.05)))
            conversions = int(max(0, clicks * cvr * rng.normal(1.0, 0.08)))

            rows.append(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "channel": channel,
                    "spend": round(spend, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                }
            )

    df = pd.DataFrame(rows)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    return df


def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "channel"]).reset_index(drop=True)
    return df


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ctr"] = out["clicks"] / out["impressions"].replace(0, np.nan)
    out["cvr"] = out["conversions"] / out["clicks"].replace(0, np.nan)
    out["cpa"] = out["spend"] / out["conversions"].replace(0, np.nan)
    out["conv_per_dollar"] = out["conversions"] / out["spend"].replace(0, np.nan)
    return out


def trailing_metrics(history: pd.DataFrame, as_of_date: pd.Timestamp, window_days: int = 3) -> pd.DataFrame:
    start_date = as_of_date - pd.Timedelta(days=window_days - 1)
    hist = history[(history["date"] >= start_date) & (history["date"] <= as_of_date)].copy()
    grouped = (
        hist.groupby("channel", as_index=False)
        .agg(
            spend=("spend", "sum"),
            impressions=("impressions", "sum"),
            clicks=("clicks", "sum"),
            conversions=("conversions", "sum"),
        )
        .sort_values("channel")
    )
    grouped = enrich(grouped)
    grouped["ctr"] = grouped["ctr"].fillna(0.0)
    grouped["cvr"] = grouped["cvr"].fillna(0.0)
    grouped["conv_per_dollar"] = grouped["conv_per_dollar"].fillna(0.0)
    return grouped


def normalize(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi - lo < 1e-9:
        return pd.Series(np.ones(len(series)), index=series.index)
    return (series - lo) / (hi - lo)


def cap_and_rebalance(target: pd.Series, previous: pd.Series, total_budget: float, floor_share: float = 0.20, max_share: float = 0.60, cap_pct: float = 0.20) -> pd.Series:
    floor = total_budget * floor_share
    ceiling = total_budget * max_share
    lower = np.maximum(previous * (1 - cap_pct), floor)
    upper = np.minimum(previous * (1 + cap_pct), ceiling)
    alloc = target.copy().clip(lower=lower, upper=upper)

    for _ in range(10):
        diff = total_budget - alloc.sum()
        if abs(diff) < 1e-6:
            break
        if diff > 0:
            slack = (upper - alloc).clip(lower=0)
        else:
            slack = (alloc - lower).clip(lower=0)
        slack_sum = slack.sum()
        if slack_sum <= 1e-9:
            break
        alloc += diff * (slack / slack_sum)
        alloc = alloc.clip(lower=lower, upper=upper)

    # Tiny numerical correction.
    if abs(total_budget - alloc.sum()) > 1e-6:
        remaining = total_budget - alloc.sum()
        idx = alloc.index[0]
        alloc.loc[idx] += remaining
    return alloc.round(2)


def propose_budget(history: pd.DataFrame, next_total_budget: float, current_budget: pd.Series) -> tuple[pd.DataFrame, pd.Series, str]:
    metrics = history.copy().set_index("channel").reindex(CHANNELS)
    metrics["score"] = (
        0.75 * normalize(metrics["conv_per_dollar"].fillna(0.0))
        + 0.25 * normalize(metrics["ctr"].fillna(0.0))
    )

    exploration_share = 0.10
    target_share = exploration_share / len(CHANNELS) + (1 - exploration_share) * (
        metrics["score"] / metrics["score"].sum()
    )
    target_budget = target_share * next_total_budget
    final_budget = cap_and_rebalance(target_budget, current_budget, next_total_budget)

    decision_rows = []
    rationale_bits = []
    for channel in CHANNELS:
        prev = current_budget[channel]
        new = final_budget[channel]
        delta_pct = (new - prev) / prev * 100 if prev else 0.0
        cpd = metrics.loc[channel, "conv_per_dollar"]
        ctr = metrics.loc[channel, "ctr"] * 100
        direction = "up" if new > prev else "down" if new < prev else "flat"
        reason = (
            f"{channel} {direction} {abs(delta_pct):.1f}% | conv/$={cpd:.3f}, CTR={ctr:.2f}% "
            f"based on trailing 3-day performance"
        )
        decision_rows.append(
            {
                "channel": channel,
                "previous_budget": round(prev, 2),
                "recommended_budget": round(new, 2),
                "delta_pct": round(delta_pct, 2),
                "score": round(metrics.loc[channel, "score"], 3),
                "reason": reason,
            }
        )
        rationale_bits.append(reason)
    return pd.DataFrame(decision_rows), final_budget, " ; ".join(rationale_bits)


def estimate_conversions(day_rows: pd.DataFrame, allocation: pd.Series) -> float:
    # Offline evaluator using actual same-day efficiency plus mild diminishing returns.
    est = 0.0
    for _, row in day_rows.iterrows():
        channel = row["channel"]
        actual_spend = max(row["spend"], 1e-6)
        eff = row["conversions"] / actual_spend
        scale_ratio = max(allocation[channel], 1e-6) / actual_spend
        saturation = scale_ratio ** -0.10
        est += eff * allocation[channel] * saturation
    return float(est)


def run_backtest(csv_path: str, out_dir: str, warmup_days: int = 3):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    df = enrich(load_data(csv_path))
    dates = sorted(df["date"].unique())
    decisions = []
    evaluations = []

    previous_budget = (
        df[df["date"] == dates[warmup_days - 1]].set_index("channel")["spend"].reindex(CHANNELS)
    )

    for idx in range(warmup_days, len(dates)):
        decision_date = dates[idx]
        history = trailing_metrics(df[df["date"] < decision_date], dates[idx - 1], window_days=3)
        today_rows = df[df["date"] == decision_date].copy().sort_values("channel")
        total_budget = today_rows["spend"].sum()
        equal_budget = pd.Series(total_budget / len(CHANNELS), index=CHANNELS)

        decision_df, agent_budget, rationale = propose_budget(history, total_budget, previous_budget)
        decision_df.insert(0, "date", decision_date.strftime("%Y-%m-%d"))
        decisions.append(decision_df)

        agent_est_conv = estimate_conversions(today_rows, agent_budget)
        baseline_est_conv = estimate_conversions(today_rows, equal_budget)
        agent_cpa = total_budget / max(agent_est_conv, 1e-6)
        baseline_cpa = total_budget / max(baseline_est_conv, 1e-6)

        evaluations.append(
            {
                "date": decision_date.strftime("%Y-%m-%d"),
                "total_budget": round(total_budget, 2),
                "agent_estimated_conversions": round(agent_est_conv, 2),
                "baseline_estimated_conversions": round(baseline_est_conv, 2),
                "agent_estimated_cpa": round(agent_cpa, 2),
                "baseline_estimated_cpa": round(baseline_cpa, 2),
                "rationale": rationale,
            }
        )
        previous_budget = agent_budget

    decisions_df = pd.concat(decisions, ignore_index=True)
    eval_df = pd.DataFrame(evaluations)

    summary = {
        "days_evaluated": int(len(eval_df)),
        "total_agent_estimated_conversions": round(eval_df["agent_estimated_conversions"].sum(), 2),
        "total_baseline_estimated_conversions": round(eval_df["baseline_estimated_conversions"].sum(), 2),
        "conversion_lift_pct": round(
            ((eval_df["agent_estimated_conversions"].sum() / eval_df["baseline_estimated_conversions"].sum()) - 1) * 100,
            2,
        ),
        "avg_agent_estimated_cpa": round(eval_df["agent_estimated_cpa"].mean(), 2),
        "avg_baseline_estimated_cpa": round(eval_df["baseline_estimated_cpa"].mean(), 2),
    }

    decisions_df.to_csv(out_path / "budget_recommendations.csv", index=False)
    eval_df.to_csv(out_path / "evaluation_log.csv", index=False)
    with open(out_path / "evaluation_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    make_plots(decisions_df, eval_df, out_path)
    write_run_snapshot(summary, out_path)
    return decisions_df, eval_df, summary


def make_plots(decisions_df: pd.DataFrame, eval_df: pd.DataFrame, out_path: Path):
    plt.figure(figsize=(8, 4.6))
    plt.plot(eval_df["date"], eval_df["agent_estimated_conversions"], marker="o", label="Agent")
    plt.plot(eval_df["date"], eval_df["baseline_estimated_conversions"], marker="o", label="Equal-split baseline")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Estimated daily conversions")
    plt.title("Ad Optimization Agent vs Baseline")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path / "conversion_comparison.png", dpi=200)
    plt.close()

    pivot = decisions_df.pivot(index="date", columns="channel", values="recommended_budget").reindex(columns=CHANNELS)
    plt.figure(figsize=(8, 4.6))
    for channel in CHANNELS:
        plt.plot(pivot.index, pivot[channel], marker="o", label=channel)
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Recommended budget")
    plt.title("Recommended Budget by Channel")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path / "recommended_budgets.png", dpi=200)
    plt.close()


def write_run_snapshot(summary: dict, out_path: Path):
    snapshot = textwrap.dedent(
        f"""
        Successful run snapshot
        -----------------------
        Days evaluated: {summary['days_evaluated']}
        Total estimated conversions (agent): {summary['total_agent_estimated_conversions']}
        Total estimated conversions (baseline): {summary['total_baseline_estimated_conversions']}
        Conversion lift vs baseline: {summary['conversion_lift_pct']}%
        Avg estimated CPA (agent): ${summary['avg_agent_estimated_cpa']}
        Avg estimated CPA (baseline): ${summary['avg_baseline_estimated_cpa']}
        """
    ).strip()
    (out_path / "successful_run.txt").write_text(snapshot, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Minimal ad optimization agent prototype")
    parser.add_argument("--csv", default="mock_ad_data.csv", help="Path to input CSV")
    parser.add_argument("--output_dir", default="outputs", help="Directory for run artifacts")
    parser.add_argument("--generate_mock", action="store_true", help="Generate mock CSV before running")
    parser.add_argument("--days", type=int, default=21, help="Days of mock data to generate")
    args = parser.parse_args()

    if args.generate_mock:
        generate_mock_data(args.csv, days=args.days)

    decisions_df, eval_df, summary = run_backtest(args.csv, args.output_dir)
    print("Run complete")
    print(json.dumps(summary, indent=2))
    print("\nTop recommendations sample:")
    print(decisions_df.head(6).to_string(index=False))
    print("\nEvaluation sample:")
    print(eval_df.head(5)[["date", "agent_estimated_conversions", "baseline_estimated_conversions", "agent_estimated_cpa", "baseline_estimated_cpa"]].to_string(index=False))


if __name__ == "__main__":
    main()
