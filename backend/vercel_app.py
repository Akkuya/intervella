"""Public student Function only; no operator, ingestion, migration or seed startup."""

from app.hosting import create_vercel_app

app = create_vercel_app()
