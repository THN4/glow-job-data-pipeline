"""Run the complete Market workflow on one EC2 worker, or preview it offline."""

import argparse
from datetime import date
import json
from pathlib import Path

from src.market.config.logging import configure_logging
from src.market.scheduled_pipeline import PROJECT_ROOT, WorkerBusyError, build_plan, execute_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true", help="Start a new run; may call JSearch/Nova 2 Lite and write S3/DB")
    source.add_argument("--resume-run-id", help="Resume this runner's saved journal; missing queries/skills may call APIs")
    parser.add_argument("--dry-run", action="store_true", help="Read local config/journal only; no lock, API or DB calls/writes")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--raw-storage", choices=("s3", "local"), help="Default s3; local must be explicitly selected")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--window-days", type=int, help="Inclusive UTC window ending today; defaults to validation.time_window_days")
    parser.add_argument("--date-basis", choices=("first_seen_at", "posted_at"), help="Default first_seen_at")
    parser.add_argument("--skill-request-interval", type=float)
    args = parser.parse_args()
    options = {name: getattr(args, name) for name in (
        "data_dir", "resume_run_id", "raw_storage", "start_date", "end_date",
        "window_days", "date_basis", "skill_request_interval",
    )}
    try:
        # This loads .env before configuring the shared logger.
        plan = build_plan(**options)
        if args.dry_run:
            print(json.dumps({"status": "dry_run", "plan": plan,
                              "note": "No API or DB calls/writes. This preview run ID is not reserved."}, indent=2))
            return 0
        configure_logging()
        result = execute_run(**options)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except WorkerBusyError:
        parser.exit(75, "Another Market run is active on this worker; this invocation was skipped.\n")
    except ValueError as error:
        parser.exit(1, f"Market validation failed: {error}\n")
    except (OSError, KeyError) as error:
        parser.exit(1, f"Market run could not finish ({type(error).__name__}). Check local configuration and the run journal.\n")
    except Exception as error:
        parser.exit(1, f"Market run failed ({type(error).__name__}). Inspect data/processed/pipeline_runs and resume the same run ID.\n")


if __name__ == "__main__":
    raise SystemExit(main())
