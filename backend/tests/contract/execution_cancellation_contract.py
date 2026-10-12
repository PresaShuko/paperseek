"""A cancelled caller stays cancelled even when the thread it waited for then fails."""
import asyncio
import threading
import unittest

from paperseek_app.execution import run_blocking


class RunBlockingCancellationContract(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_thread_does_not_replace_the_cancellation(self) -> None:
        started, release = threading.Event(), threading.Event()

        def fail_after_release() -> None:
            started.set()
            release.wait(5)
            raise RuntimeError("storage failed")

        task = asyncio.create_task(run_blocking(fail_after_release))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        release.set()
        # A worker loop that catches storage errors would otherwise never stop.
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
