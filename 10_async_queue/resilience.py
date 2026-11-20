"""
Async processing + resilience patterns (Module 10, slides 11 & 13).

Models the slide-11 flow — client gets an immediate job ID, requests land in a
queue (load leveling), a worker pool drains it — plus the slide-13 resilience
patterns:
  - Exponential backoff with jitter (retry delays)
  - Circuit breaker (stop hammering a failing dependency)

Pure in-memory simulation so it runs locally without SQS/Lambda. The worker's
"call" can be a real Bedrock invocation or a simulated one with an injectable
failure rate.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"      # circuit open -> fast-fail


@dataclass
class Job:
    id: str
    prompt: str
    state: JobState = JobState.QUEUED
    attempts: int = 0
    result: str = ""
    error: str = ""
    delays: list[float] = field(default_factory=list)  # backoff delays applied


def new_job(prompt: str) -> Job:
    """Create a job with an immediate job ID (slide 11: 'immediate job ID return')."""
    return Job(id=str(uuid.uuid4())[:8], prompt=prompt)


# --- exponential backoff with jitter (slide 13) ------------------------------
def backoff_delay(attempt: int, base: float = 0.2, cap: float = 5.0,
                  jitter: bool = True) -> float:
    """Full-jitter exponential backoff: random(0, min(cap, base * 2**attempt))."""
    ceiling = min(cap, base * (2 ** attempt))
    return random.uniform(0, ceiling) if jitter else ceiling


# --- circuit breaker (slide 13) ----------------------------------------------
class CircuitState(str, Enum):
    CLOSED = "closed"      # healthy, calls pass through
    OPEN = "open"          # failing, calls fast-fail
    HALF_OPEN = "half_open"  # probing recovery


@dataclass
class CircuitBreaker:
    fail_threshold: int = 5         # consecutive failures to trip open
    cooldown_s: float = 3.0         # how long to stay open before probing
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0

    def allow(self) -> bool:
        if self.state == CircuitState.OPEN:
            if time.time() - self.opened_at >= self.cooldown_s:
                self.state = CircuitState.HALF_OPEN
                return True  # allow one probe
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.fail_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()


@dataclass
class Stats:
    succeeded: int = 0
    failed: int = 0
    rejected: int = 0
    total_attempts: int = 0
    total_retry_delay: float = 0.0


def process_job(
    job: Job,
    call,
    breaker: CircuitBreaker,
    stats: Stats,
    *,
    max_attempts: int = 4,
    sleep=time.sleep,
) -> Job:
    """Drain one job through the breaker + retry/backoff loop.

    `call(prompt) -> str` performs the actual work and raises on failure.
    """
    job.state = JobState.RUNNING
    for attempt in range(max_attempts):
        if not breaker.allow():
            if job.attempts == 0:
                # Never started: the circuit was already open -> fast-fail reject.
                job.state = JobState.REJECTED
                job.error = "circuit open (fast-fail)"
                stats.rejected += 1
                return job
            # Already attempted and failing; stop retrying once the circuit opens.
            job.state = JobState.FAILED
            stats.failed += 1
            return job

        job.attempts += 1
        stats.total_attempts += 1
        try:
            job.result = call(job.prompt)
            job.state = JobState.SUCCEEDED
            breaker.record_success()
            stats.succeeded += 1
            return job
        except Exception as e:  # noqa: BLE001 - simulated/real failure
            job.error = str(e)
            breaker.record_failure()
            if attempt < max_attempts - 1:
                delay = backoff_delay(attempt)
                job.delays.append(round(delay, 3))
                stats.total_retry_delay += delay
                sleep(delay)
            else:
                job.state = JobState.FAILED
                stats.failed += 1
    return job
