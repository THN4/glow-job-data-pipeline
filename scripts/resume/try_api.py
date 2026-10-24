"""Walks through the whole API flow like the frontend will: upload -> extract -> poll.

    python -m scripts.resume.try_api path/to/cv.pdf

Requires the API to be running (uvicorn app.main:app --port 8787). Override the address with API=...
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

API = os.environ.get("API", "http://localhost:8787/api")
TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def main(path: str) -> None:
    file = Path(path)
    data = file.read_bytes()
    content_type = TYPES.get(file.suffix.lower(), "application/octet-stream")
    session_id = str(uuid.uuid4())

    with httpx.Client(timeout=30) as c:
        print(f"1) Request upload ({content_type}, {len(data)} bytes)")
        r = c.post(f"{API}/cv/uploads", json={"fileName": file.name, "contentType": content_type, "size": len(data)})
        r.raise_for_status()
        upload = r.json()

        print("2) Upload file")
        target = upload["upload"]
        r = c.request(target["method"], target["url"], content=data, headers=target.get("headers"))
        if r.status_code >= 400:
            sys.exit(f"upload failed: {r.status_code} {r.text}")

        print("3) Start extraction")
        r = c.post(f"{API}/cv/extractions", json={"uploadId": upload["uploadId"], "sessionId": session_id})
        r.raise_for_status()
        job_id = r.json()["jobId"]

        print(f"4) Poll {job_id}")
        started, last = time.monotonic(), ""
        while True:
            job = c.get(f"{API}/cv/extractions/{job_id}", headers={"X-Session-Id": session_id}).json()
            if job["stage"] != last:
                print(f"   {time.monotonic() - started:4.0f} s  {job['status']} / {job['stage']}")
                last = job["stage"]
            if job["status"] in ("succeeded", "failed"):
                print(json.dumps(job, indent=2, ensure_ascii=False))
                return
            time.sleep(1.5)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m scripts.resume.try_api <cv.pdf|cv.png|cv.jpg>")
    main(sys.argv[1])
