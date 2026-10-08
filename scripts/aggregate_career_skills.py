"""Refresh career skill statistics for a UTC window and selected date basis."""

import argparse
from datetime import date

from src.load.career_skill_aggregator import refresh_career_skill_stats


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_date", type=_date)
    parser.add_argument("end_date", type=_date)
    parser.add_argument(
        "--date-basis",
        choices=("posted_at", "first_seen_at"),
        default="posted_at",
        help="Use publication date, or when the pipeline first found the job",
    )
    arguments = parser.parse_args()
    print(
        refresh_career_skill_stats(
            arguments.start_date,
            arguments.end_date,
            date_basis=arguments.date_basis,
        )
    )


if __name__ == "__main__":
    main()
