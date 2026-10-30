"""Hash a new private beta passcode without exposing it in process arguments/history."""

import getpass
import sys

from app.db import create_db_engine, database_url
from app.student_auth.config import AuthConfig
from app.student_auth.service import activate_policy, password_hash


def main():
    if sys.argv[1:] == ["activate"]:
        config = AuthConfig.from_environment()
        runtime = database_url("STUDENT_AUTH_DATABASE_URL")
        admin = database_url("STUDENT_AUTH_ADMIN_DATABASE_URL")
        if (runtime.host, runtime.port or 5432, runtime.database, runtime.query) != (
            admin.host,
            admin.port or 5432,
            admin.database,
            admin.query,
        ):
            raise SystemExit("Admin and runtime connections must target the same auth database.")
        engine = create_db_engine("STUDENT_AUTH_ADMIN_DATABASE_URL")
        try:
            activate_policy(engine, config)
        finally:
            engine.dispose()
        print("Student policy activated; all previous student sessions revoked.")
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: python -m app.student_auth [activate]")
    password = getpass.getpass("New beta passcode (12–256 characters): ")
    confirmation = getpass.getpass("Repeat passcode: ")
    if password != confirmation:
        raise SystemExit("Passcodes differ; nothing generated.")
    print(password_hash(password))


if __name__ == "__main__":
    main()
