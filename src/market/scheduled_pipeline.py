"""One-worker Market run planning, locking, journals and full-stage execution."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import os
from pathlib import Path

from src.market.config.settings import load_settings
from src.market.ingestion.raw_storage import validate_run_id
from src.market.run_artifacts import RunArtifactStore
from src.market.pipeline import run_pipeline
from src.market.skill_extraction.extractor import EXTRACTION_PROMPT_VERSION
from src.shared.db.database import get_database_connection
from src.shared.llm.bedrock_client import BedrockTextSettings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class WorkerBusyError(RuntimeError):
    """Another command holds the same worker's lock."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def worker_lock(path: Path):
    """An OS lock releases on process exit; a leftover file is not a stale lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WorkerBusyError("Another Market run holds this worker lock") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def build_plan(
    *, data_dir: Path, resume_run_id: str | None = None,
    raw_storage: str | None = None, start_date: date | None = None,
    end_date: date | None = None, window_days: int | None = None,
    date_basis: str | None = None, skill_request_interval: float | None = None,
) -> dict:
    """Read configuration/local journal only. No DB, AWS or model calls."""
    settings = load_settings()
    data_dir = data_dir.resolve()
    bucket = os.getenv("RAW_S3_BUCKET", "").strip()
    prefix = os.getenv("RAW_S3_PREFIX", "raw/jsearch").strip("/") or "raw/jsearch"
    configuration = {
        "settings": asdict(settings), "skill_prompt_version": EXTRACTION_PROMPT_VERSION,
        "query_order": [(slug, query) for slug, career in settings.careers.items() for query in career.queries],
        "skill_model": BedrockTextSettings().model_id,
        "aws_region": os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION", ""),
        "database": {key: os.getenv(key, "") for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER")},
        "data_dir": str(data_dir),
    }
    fingerprint = sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    runs_dir = data_dir / "processed" / "pipeline_runs"
    if resume_run_id:
        validate_run_id(resume_run_id)
        if any(value is not None for value in (
            raw_storage, start_date, end_date, window_days, date_basis, skill_request_interval,
        )):
            raise ValueError("Resume uses its saved storage/window/options; do not supply replacements")
        state_path = runs_dir / resume_run_id / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        plan = state["plan"]
        if (plan.get("schema_version") != "scheduled-market-run-1"
                or plan.get("run_id") != resume_run_id
                or plan.get("configuration_sha256") != fingerprint):
            raise ValueError("Resume configuration changed; restore the original config or start a new run")
        expected_paths = {
            "state_path": state_path, "raw_output_dir": data_dir / "raw",
            "skill_output_dir": data_dir / "processed" / "skill_extraction",
            "company_review_output_dir": data_dir / "processed" / "company_match_candidates",
        }
        if any(Path(plan[name]).resolve() != expected.resolve() for name, expected in expected_paths.items()):
            raise ValueError("Resume paths do not match this data directory")
        if plan["raw_storage"] == "s3" and (plan["s3_bucket"] != bucket or plan["s3_prefix"] != prefix):
            raise ValueError("Resume S3 bucket/prefix differs from the saved run")
        if plan["date_basis"] not in {"posted_at", "first_seen_at"} or plan["raw_storage"] not in {"s3", "local"}:
            raise ValueError("Invalid options in the saved plan")
        if date.fromisoformat(plan["start_date"]) > date.fromisoformat(plan["end_date"]):
            raise ValueError("Invalid date window in the saved plan")
        if not math.isfinite(plan["skill_request_interval"]) or plan["skill_request_interval"] < 0:
            raise ValueError("Invalid request interval in the saved plan")
        return plan
    if (start_date is None) != (end_date is None):
        raise ValueError("Supply both --start-date and --end-date")
    if start_date is not None and window_days is not None:
        raise ValueError("Use an explicit date pair or --window-days")
    days = window_days if window_days is not None else settings.validation.time_window_days
    if days < 1:
        raise ValueError("window_days must be positive")
    end = end_date or datetime.now(timezone.utc).date()
    start = start_date or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    basis = date_basis or "first_seen_at"
    if basis not in {"posted_at", "first_seen_at"}:
        raise ValueError("Invalid date basis")
    storage = raw_storage or "s3"
    if storage not in {"local", "s3"}:
        raise ValueError("Invalid raw storage")
    if storage == "s3" and not bucket:
        raise ValueError("S3 mode requires RAW_S3_BUCKET; use --raw-storage local explicitly for local output")
    interval = skill_request_interval if skill_request_interval is not None else 10.0
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("skill_request_interval must be finite and non-negative")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return {
        "schema_version": "scheduled-market-run-1", "run_id": run_id,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "date_basis": basis, "window_timezone": "UTC",
        "raw_storage": storage, "s3_bucket": bucket if storage == "s3" else None,
        "s3_prefix": prefix if storage == "s3" else None,
        "skill_request_interval": interval, "configuration_sha256": fingerprint,
        "expected_queries": sum(len(c.queries) for c in settings.careers.values()),
        "raw_output_dir": str(data_dir / "raw"),
        "skill_output_dir": str(data_dir / "processed" / "skill_extraction"),
        "company_review_output_dir": str(data_dir / "processed" / "company_match_candidates"),
        "state_path": str(runs_dir / run_id / "state.json"),
    }


def _preflight() -> None:
    """Fail early for missing credentials/schema/reference data before API spend."""
    settings = load_settings()
    if not os.getenv(settings.jsearch.api_key_env, "").strip() and not os.getenv("JSEARCH_SECRET_ID", "").strip():
        raise ValueError("Configure the JSearch API key or JSEARCH_SECRET_ID")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise ValueError("Market skill extraction requires GEMINI_API_KEY")
    with get_database_connection() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        for relation in ("core.skills", "core.career_profiles", "core.companies", "market.job_postings",
                         "market.job_skills", "market.career_skill_stats"):
            if connection.execute("SELECT to_regclass(%s)", (relation,)).fetchone()[0] is None:
                raise ValueError(f"Apply database migrations first: missing {relation}")
        profiles = {row[0] for row in connection.execute(
            "SELECT slug FROM core.career_profiles WHERE is_active"
        ).fetchall()}
        missing = {f"{slug}_general" for slug in settings.careers} - profiles
        if missing:
            raise ValueError("Seed active career profiles first: " + ", ".join(sorted(missing)))
        if not connection.execute("SELECT EXISTS(SELECT 1 FROM core.skills WHERE catalog_status='approved')").fetchone()[0]:
            raise ValueError("An approved skill catalog is required before scheduled loading")


def execute_run(*, data_dir: Path, resume_run_id: str | None = None, **options) -> dict:
    """Run under a worker lock; journal progress even when a later stage fails."""
    data_dir = data_dir.resolve()
    with worker_lock(data_dir / "processed" / "pipeline_runs" / ".worker.lock"):
        if resume_run_id:
            validate_run_id(resume_run_id)
            state_path = data_dir / "processed" / "pipeline_runs" / resume_run_id / "state.json"
            if not state_path.is_file():
                load_settings()  # Load .env only for the live recovery path.
                bucket = os.getenv("RAW_S3_BUCKET", "").strip()
                if bucket:
                    RunArtifactStore(bucket, resume_run_id).restore_missing("state.json", state_path)
        plan = build_plan(data_dir=data_dir, resume_run_id=resume_run_id, **options)
        state_path = Path(plan["state_path"])
        artifacts = RunArtifactStore(plan["s3_bucket"], plan["run_id"]) if plan["s3_bucket"] else None
        if resume_run_id and artifacts:
            artifacts.restore_missing("skill_checkpoint.json", Path(plan["skill_output_dir"]) / f"{plan['run_id']}.json")
            artifacts.restore_missing("company_candidates.csv", Path(plan["company_review_output_dir"]) / f"{plan['run_id']}.csv")
        state = json.loads(state_path.read_text(encoding="utf-8")) if resume_run_id else {
            "plan": plan, "created_at": _now(), "attempts": [],
        }
        if state.get("status") in {"completed", "no_jobs"}:
            return {**state["result"], "already_completed": True}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        attempt = {"started_at": _now(), "status": "running"}
        if state["attempts"] and state["attempts"][-1]["status"] == "running":
            state["attempts"][-1]["status"] = "interrupted"
        state["attempts"].append(attempt)
        state.pop("error_type", None)
        log_path = state_path.parent / f"attempt-{len(state['attempts']):03d}.log"
        attempt["log_path"] = str(log_path)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        def progress(stage):
            state.update(status="running", stage=stage, updated_at=_now())
            _write_json(state_path, state)
            if artifacts:
                artifacts.upload("state.json", state_path)
            logger.info("Market stage: run_id=%s stage=%s", plan["run_id"], stage)

        def artifact_saved(name: str, path: Path) -> None:
            if artifacts:
                artifacts.upload(name, path)

        # Freeze S3 selection for this process, even when local mode overrides
        # a .env file that enables S3. load_dotenv does not override these values.
        old_bucket, old_prefix = os.environ.get("RAW_S3_BUCKET"), os.environ.get("RAW_S3_PREFIX")
        os.environ["RAW_S3_BUCKET"] = plan["s3_bucket"] or ""
        os.environ["RAW_S3_PREFIX"] = plan["s3_prefix"] or "raw/jsearch"
        try:
            logger.info("Market run: run_id=%s journal=%s", plan["run_id"], state_path)
            progress("preflight")
            _preflight()
            result = run_pipeline(
                live=True, new_run_id=plan["run_id"], resume_raw=bool(resume_run_id),
                start_date=date.fromisoformat(plan["start_date"]),
                end_date=date.fromisoformat(plan["end_date"]), date_basis=plan["date_basis"],
                skill_request_interval=plan["skill_request_interval"],
                raw_output_dir=Path(plan["raw_output_dir"]),
                skill_output_dir=Path(plan["skill_output_dir"]),
                company_review_output_dir=Path(plan["company_review_output_dir"]), progress=progress,
                artifact_saved=artifact_saved if artifacts else None,
            )
            status = "completed" if result["processed_jobs"] else "no_jobs"
            warnings = []
            loaded = result["loaded"]
            if loaded.get("postings_loaded", 0) and not loaded.get("skills_loaded", 0):
                warnings.append("Postings loaded but no verified catalog-matched skills were stored; inspect JD coverage and skill checkpoints.")
            if loaded.get("unmatched_skills", 0):
                warnings.append("Unmatched skill names remain in the checkpoint for catalog review; they were not created automatically.")
            result.update(status=status, warnings=warnings, state_path=str(state_path), log_path=str(log_path))
            state.update(status=status, stage="finished", result=result)
            attempt.update(status=status, finished_at=_now())
            summary_path = state_path.with_name("summary.json")
            _write_json(summary_path, result)
            if artifacts:
                artifacts.upload("summary.json", summary_path)
            logger.info("Market finished: run_id=%s status=%s", plan["run_id"], status)
            return result
        except BaseException as error:
            state["status"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            attempt.update(status=state["status"], finished_at=_now(), error_type=type(error).__name__)
            state["error_type"] = type(error).__name__
            logger.error("Market failed: run_id=%s stage=%s error_type=%s; resume the same run",
                         plan["run_id"], state.get("stage"), type(error).__name__)
            if isinstance(error, ValueError):
                # Validation messages contain local config/schema issues, not
                # provider response bodies or database connection credentials.
                logger.error("Validation: %s", error)
            raise
        finally:
            try:
                state["updated_at"] = _now()
                _write_json(state_path, state)
                if artifacts:
                    artifacts.upload("state.json", state_path)
            finally:
                logging.getLogger().removeHandler(handler)
                handler.close()
                for key, previous in (("RAW_S3_BUCKET", old_bucket), ("RAW_S3_PREFIX", old_prefix)):
                    if previous is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous
