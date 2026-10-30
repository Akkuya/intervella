"""Refuse a Vercel release if pulled settings identify a non-staging project."""

import json
import os
import re
from pathlib import Path


def verify_staging_project(project: dict, project_id: str, org_id: str):
    if (
        not project_id
        or not org_id
        or project.get("projectId") != project_id
        or project.get("orgId") != org_id
        or not re.fullmatch(r"intervella-staging(?:-[a-z0-9-]+)?", project.get("projectName", ""))
    ):
        raise ValueError("Expected the dedicated Intervella synthetic staging project")


if __name__ == "__main__":
    project = json.loads(Path(".vercel/project.json").read_text(encoding="utf-8"))
    verify_staging_project(project, os.environ["VERCEL_PROJECT_ID"], os.environ["VERCEL_ORG_ID"])
    print("Dedicated synthetic staging project verified.")
