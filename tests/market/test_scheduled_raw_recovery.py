"""Partial ingestion and S3 recovery without network access or AWS credentials."""

from datetime import datetime, timezone
from io import BytesIO
import json

import boto3
from botocore.exceptions import ClientError
import pytest
from requests import HTTPError

from src.market.config.settings import CareerSettings, load_settings
from src.market.ingestion.extract_jobs import extract_jobs
from src.market.ingestion.raw_storage import load_saved_query, save_raw_result, save_raw_result_to_s3


RUN_ID = "20261024T235900000000Z"


@pytest.fixture
def settings():
    source = load_settings()
    source.careers.clear()
    source.careers["data_engineer"] = CareerSettings("Data Engineer", ("Data Engineer", "Data Pipeline Engineer"))
    return source


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.fail_upload = False
        self.deny_list = False

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        if self.fail_upload:
            self.fail_upload = False
            raise RuntimeError("simulated upload interruption")
        self.objects[(Bucket, Key)] = Body

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
        if self.deny_list:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListObjectsV2")
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in keys[:MaxKeys]]}

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


@pytest.fixture
def s3(monkeypatch):
    service = MemoryS3()
    monkeypatch.setattr(boto3, "client", lambda name: service)
    return service


def record():
    return {"career_slug": "data_engineer", "career_name": "Data Engineer", "query": "Data Engineer",
            "response": {"status": "OK", "data": {"jobs": []}}}


def test_raw_date_is_run_start_day_even_after_midnight(tmp_path):
    path = save_raw_result(record(), tmp_path, RUN_ID, 1,
                           collected_at=datetime(2026, 10, 25, 0, 1, tzinfo=timezone.utc))
    assert path.parent.parent == tmp_path / "2026" / "10" / "24"
    assert json.loads(path.read_text())["collected_at"].startswith("2026-10-25")


def test_s3_restore_recreates_missing_local_raw(s3, tmp_path):
    save_raw_result_to_s3(record(), bucket="bucket", run_id=RUN_ID, query_number=1)
    saved = load_saved_query(output_dir=tmp_path, run_id=RUN_ID, query_number=1,
                            career_slug="data_engineer", query="Data Engineer", s3_bucket="bucket")
    assert saved["response"]["status"] == "OK"
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_missing_s3_key_is_allowed_but_access_denied_is_not(s3, tmp_path):
    options = dict(output_dir=tmp_path, run_id=RUN_ID, query_number=1,
                   career_slug="data_engineer", query="Data Engineer", s3_bucket="bucket")
    assert load_saved_query(**options) is None
    s3.deny_list = True
    with pytest.raises(ClientError):
        load_saved_query(**options)


def test_saved_query_mismatch_fails_instead_of_reusing_wrong_response(tmp_path):
    save_raw_result(record(), tmp_path, RUN_ID, 1)
    with pytest.raises(ValueError, match="does not match"):
        load_saved_query(output_dir=tmp_path, run_id=RUN_ID, query_number=1,
                         career_slug="data_engineer", query="Different query")


def test_resume_fetches_only_missing_queries(settings, monkeypatch, tmp_path):
    calls = []

    def request(**options):
        calls.append(options["query"])
        if len(calls) == 2:
            raise HTTPError("simulated request interruption")
        return {"status": "OK", "data": []}

    monkeypatch.setattr("src.market.ingestion.extract_jobs.extract_single_query", request)
    with pytest.raises(HTTPError):
        extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID)
    results = extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID, resume_raw=True)
    assert len(results) == 2
    assert calls == ["Data Engineer", "Data Pipeline Engineer", "Data Pipeline Engineer"]


def test_s3_upload_failure_keeps_raw_and_resume_avoids_another_api_call(settings, s3, monkeypatch, tmp_path):
    calls = []

    def request(**options):
        calls.append(options["query"])
        return {"status": "OK", "data": []}

    monkeypatch.setattr("src.market.ingestion.extract_jobs.extract_single_query", request)
    s3.fail_upload = True
    with pytest.raises(RuntimeError, match="upload interruption"):
        extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID, s3_bucket="bucket")
    assert len(list(tmp_path.rglob("*.json"))) == 1
    results = extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID,
                           s3_bucket="bucket", resume_raw=True)
    assert len(results) == 2
    assert calls == ["Data Engineer", "Data Pipeline Engineer"]
    assert len(s3.objects) == 2


def test_bad_api_response_is_not_no_jobs_and_is_refetched_on_resume(settings, monkeypatch, tmp_path):
    calls = []

    def request(**options):
        calls.append(options["query"])
        return {"status": "ERROR" if len(calls) == 1 else "OK", "data": []}

    monkeypatch.setattr("src.market.ingestion.extract_jobs.extract_single_query", request)
    with pytest.raises(ValueError, match="unsuccessful or malformed"):
        extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID)
    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert len(extract_jobs(settings, output_dir=tmp_path, run_id=RUN_ID, resume_raw=True)) == 2
    assert calls == ["Data Engineer", "Data Engineer", "Data Pipeline Engineer"]
