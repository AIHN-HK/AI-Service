"""
Background Task Manager — Fire-and-forget task tracking.

Wraps asyncio.create_task with:
- Automatic error logging (silent, non-fatal)
- Task set tracking (prevents GC before completion)
- Named tasks for debugging
- Bounded task cap to prevent resource exhaustion under traffic spikes
"""

import asyncio
import logging
from typing import Coroutine, Optional, Set

logger = logging.getLogger(__name__)

_tasks: Set[asyncio.Task] = set()

# Prevents unbounded memory growth during disconnect/spike storms.
MAX_BG_TASKS = 50


def fire(coro: Coroutine, name: str = "unnamed") -> Optional[asyncio.Task]:
    """
    Schedule a coroutine as a fire-and-forget background task.

    - Task is tracked to prevent garbage collection before completion.
    - Errors are logged but never propagated (non-fatal).
    - Task is automatically removed from tracking set on completion.
    - If MAX_BG_TASKS is reached, coro is dropped safely (no leak).

    Args:
        coro: The coroutine to run in the background.
        name: A descriptive name for logging.

    Returns:
        The created asyncio.Task, or None if the cap was reached.
    """
    if len(_tasks) >= MAX_BG_TASKS:
        logger.warning(
            f"[BG] Max background tasks reached ({MAX_BG_TASKS}), dropping '{name}'. "
            f"Consider raising MAX_BG_TASKS or investigating slow tasks."
        )
        coro.close()  # Cleanup unawaited coroutine to avoid ResourceWarning
        return None

    task = asyncio.create_task(coro, name=f"bg:{name}")
    _tasks.add(task)

    def _on_done(t: asyncio.Task):
        _tasks.discard(t)
        if t.cancelled():
            logger.debug(f"[BG] Task '{name}' was cancelled")
        elif t.exception():
            logger.error(f"[BG] Task '{name}' failed: {t.exception()}", exc_info=t.exception())
        else:
            logger.debug(f"[BG] Task '{name}' completed successfully")

    task.add_done_callback(_on_done)
    return task


def pending_count() -> int:
    """Return number of currently running background tasks."""
    return len(_tasks)
