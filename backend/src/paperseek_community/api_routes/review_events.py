from pathlib import Path

from fastapi import FastAPI, Header, Request
from starlette.concurrency import run_in_threadpool

from paperseek_app.errors import RunNotFound
from paperseek_app.models import PersistedEvent
from paperseek_app.review.models import ReviewError
from paperseek_community.api_routes.event_stream import event_cursor, event_response
from paperseek_community.api_routes.reviews import open_reviews
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence.sqlite_review_jobs import SQLiteReviewUnitOfWork


def register_review_events(app: FastAPI, *, database: Path, credentials: EncryptedRunCredentialStore) -> None:
    @app.get("/api/v1/reviews/{review_id}/jobs/{job_id}/events", response_model=None,
             responses={200: {"model": PersistedEvent, "content": {"text/event-stream": {}}}})
    async def events(request: Request, review_id: str, job_id: str,
                      last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        sequence = event_cursor(last_event_id)

        def check() -> None:
            with open_reviews(database, credentials) as store:
                store.get_review_job(review_id, job_id)

        await run_in_threadpool(check)

        def open_reader():
            store = SQLiteReviewUnitOfWork(database)

            def read(after: int):
                try:
                    detail = store.get_review_job(review_id, job_id)
                except ReviewError as exc:
                    raise RunNotFound("Review job not found.") from exc
                return detail, store.list_events(job_id, after_sequence=after, limit=200)

            return read, store.close

        return event_response(request, sequence, open_reader)
