"""Load a saved skill-extraction run into PostgreSQL without API requests."""

import argparse

from src.load.job_skill_loader import load_job_skills_from_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="Run ID from data/processed/skill_extraction")
    arguments = parser.parse_args()
    print(load_job_skills_from_run(arguments.run_id))


if __name__ == "__main__":
    main()
