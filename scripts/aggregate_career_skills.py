"""Refresh career skill statistics for a posting-date window (UTC)."""

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
    arguments = parser.parse_args()
    print(refresh_career_skill_stats(arguments.start_date, arguments.end_date))


if __name__ == "__main__":
    main()
