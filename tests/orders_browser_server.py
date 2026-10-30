"""Fresh, loopback-only synthetic fixture for orders_browser_smoke.cjs.

Run as a separate process: python tests/orders_browser_server.py
See orders_browser_README.md. Never run this fixture as a deployed service.
"""

import os
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory


def serve():
    if "main" in sys.modules:
        raise RuntimeError("Start this fixture in its own Python process.")

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    # No database/host argument is accepted. Always replace inherited settings
    # before importing the application; never initialize an existing database.
    with TemporaryDirectory(prefix="fabtrace-orders-browser-") as directory:
        database = Path(directory).resolve() / "synthetic.sqlite"
        os.environ.update(
            DATABASE_URL="sqlite:///" + str(database),
            JWT_SECRET=secrets.token_urlsafe(48),
            COOKIE_SECURE="false",
            PUBLIC_BASE_URL="https://fabtrace-training.example",
        )
        import main
        from conftest import BADGES, TEST_PIN
        from permissions import role_label
        import uvicorn

        try:
            if (main.engine.url.get_backend_name() != "sqlite"
                    or Path(main.engine.url.database).resolve() != database):
                raise RuntimeError("Fixture requires its fresh temporary SQLite database.")
            main.Base.metadata.create_all(main.engine)
            with main.SessionLocal() as session:
                hashed = main.password_hash.hash(TEST_PIN)
                session.add_all(
                    main.Employee(
                        badge=badge, name="Training " + role_label(role),
                        role=role, pin_hash=hashed, active=True,
                    )
                    for role, badge in BADGES.items()
                )
                session.commit()
            print("Synthetic orders fixture: http://127.0.0.1:8782", flush=True)
            print("Temporary data is deleted when this process exits.", flush=True)
            uvicorn.run(main.app, host="127.0.0.1", port=8782, log_level="warning")
        finally:
            main.engine.dispose()


if __name__ == "__main__":
    serve()
