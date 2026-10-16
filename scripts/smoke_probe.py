"""Inside isolated Compose: BFF to ATS over real DNS, synthetic data only."""

import json
import ssl
import sys
from pathlib import Path

import httpx

from bff.config import COOKIE


def run(restart=False):
    with httpx.Client(
        base_url="https://workspace.test:8443",
        verify=ssl.create_default_context(cafile="/synthetic/pki/ca.crt"),
        trust_env=False,
        timeout=120,
        headers={
            "Host": "workspace.test:8443",
            "Origin": "https://workspace.test:8443",
            "Sec-Fetch-Site": "same-origin",
        },
    ) as browser:
        if restart:
            token = Path("/restart/smoke-session").read_text()
            browser.headers["Cookie"] = COOKIE + "=" + token
            assert browser.get("/workspace/auth/session").json()["authenticated"] is True
            csrf = browser.get("/workspace/auth/csrf").json()["csrf_token"]
            browser.headers["X-CSRF-Token"] = csrf
            assert browser.post("/workspace/auth/logout").status_code == 204
            assert browser.get("/workspace/ats/resumes").status_code == 401
            print("Restart persistence and logout revocation verified.")
            return
        for path in (
            "/api/resumes",
            "/api/admin/sources",
            "/api/resumes%2F1",
            "/api/jobs/1/../../resumes",
        ):
            assert browser.get(path).status_code == 403
        # Public reads still reach the synthetic public API, which has no health file.
        assert browser.get("/api/health").status_code == 404
        assert browser.get("/workspace/ats/resumes").status_code == 401
        response = browser.post(
            "/workspace/auth/login", json={"password": "synthetic-test-password-only"}
        )
        assert response.status_code == 200, response.text
        token = browser.cookies.get(COOKIE)
        # Secure cookie is sent by the HTTPS browser client through the real Nginx snippet.
        browser.headers["X-CSRF-Token"] = browser.get("/workspace/auth/csrf").json()["csrf_token"]
        profile = json.loads(Path("/upstream/examples/master-profile.example.json").read_text())

        def call(method, path, **kwargs):
            response = browser.request(method, "/workspace/ats" + path, **kwargs)
            assert response.status_code == 200, (path, response.status_code, response.text)
            return response

        resume = call("POST", "/resumes/import", json=profile).json()["id"]
        record = call("GET", f"/resumes/{resume}/profile").json()
        call(
            "PATCH",
            f"/resumes/{resume}/profile",
            json={
                "expected_revision": 1,
                "profile": record["profile"],
                "confirm_all": True,
                "notes": "Synthetic Docker confirmation",
            },
        )
        call("POST", "/jobs/1/requirements/analyze")
        version = call(
            "POST", "/jobs/1/resumes/tailor", json={"resume_id": resume, "language": "en"}
        ).json()
        identifier = version["id"]
        call("GET", f"/resumes/versions/{identifier}/diff")
        decisions = [
            {"id": s["id"], "decision": "accepted"}
            for s in version["suggestions"]
            if s["decision"] == "pending"
        ]
        call(
            "PATCH",
            f"/resumes/versions/{identifier}/review",
            json={"expected_revision": 1, "decisions": decisions, "notes": "Synthetic review"},
        )
        call(
            "POST",
            f"/resumes/versions/{identifier}/approve",
            json={"expected_revision": 2, "acknowledge_gaps": True, "notes": "Synthetic approval"},
        )
        call("GET", f"/resumes/versions/{identifier}/ats-report")
        for extension, mime in [
            ("pdf", "application/pdf"),
            ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]:
            exported = call("GET", f"/resumes/versions/{identifier}/export?format={extension}")
            call(
                "POST",
                "/resumes/import",
                content=exported.content,
                headers={"Content-Type": mime, "X-Filename": "synthetic." + extension},
            )
        # Persist only in the synthetic test data mount via exec caller, not browser-facing API.
        session_file = Path("/restart/smoke-session")
        session_file.write_text(token)
        session_file.chmod(0o600)
        print(
            "Browser HTTPS + Nginx allowlist + real DNS/mTLS ATS flow and PDF/DOCX roundtrip passed."
        )


if __name__ == "__main__":
    run("--restart" in sys.argv)
