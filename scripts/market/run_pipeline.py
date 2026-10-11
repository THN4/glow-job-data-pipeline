"""Run the local market pipeline from replay or a new JSearch run."""

import argparse
import json
from datetime import date

from src.market.pipeline import run_pipeline


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--replay-run-id", help="Use saved JSearch responses for this run ID"
    )
    source.add_argument(
        "--live", action="store_true", help="Start a new JSearch and Gemini run"
    )
    parser.add_argument(
        "--replay-query-count",
        type=int,
        help="Expected query count for a raw run saved under an older careers config",
    )
    parser.add_argument("--start-date", type=_date, required=True)
    parser.add_argument("--end-date", type=_date, required=True)
    parser.add_argument(
        "--date-basis",
        choices=("posted_at", "first_seen_at"),
        default="posted_at",
        help="Aggregate by provider publication date or the pipeline's first-seen date",
    )
    parser.add_argument("--skill-limit", type=int)
    parser.add_argument("--skill-request-interval", type=float, default=10.0)
    arguments = parser.parse_args()
    result = run_pipeline(
        replay_run_id=arguments.replay_run_id,
        replay_query_count=arguments.replay_query_count,
        live=arguments.live,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        date_basis=arguments.date_basis,
        skill_limit=arguments.skill_limit,
        skill_request_interval=arguments.skill_request_interval,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
