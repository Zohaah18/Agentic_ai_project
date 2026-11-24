"""Failure handling: timeout, retry, circuit breaker, cache, rate limit."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout


class TickerNotFound(Exception):
    """Valid call, but no data for this ticker. Not a provider fault: no retry, no breaker."""


class AllProvidersFailed(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


class CircuitBreaker:
    """Stops hammering a provider that keeps failing; retries after a cool-down."""

    def __init__(self, threshold=3, reset_after=60):
        self.threshold, self.reset_after = threshold, reset_after
        self.failures, self.opened_at = 0, None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return time.time() - self.opened_at >= self.reset_after  # half-open probe

    def success(self):
        self.failures, self.opened_at = 0, None

    def failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()


def run_with_timeout(fn, timeout):
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except FutTimeout:
        raise TimeoutError(f"timed out after {timeout}s")
    finally:
        ex.shutdown(wait=False)


def with_retry(fn, attempts=2, base_delay=0.5):
    last = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except TickerNotFound:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last


class TTLCache:
    def __init__(self, ttl=120):
        self.ttl, self.store = ttl, {}

    def get(self, key):
        v = self.store.get(key)
        if v and time.time() - v[0] < self.ttl:
            return v[1]
        return None

    def set(self, key, value):
        self.store[key] = (time.time(), value)


class RateLimiter:
    def __init__(self, per_minute):
        self.per_minute, self.calls, self.lock = per_minute, [], threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.per_minute:
                return False
            self.calls.append(now)
            return True


class ProviderChain:
    """Try providers in order; each has its own breaker, timeout and retries."""

    def __init__(self, providers, method, settings):
        self.providers, self.method, self.s = providers, method, settings
        self.breakers = {p.name: CircuitBreaker(settings.breaker_threshold, settings.breaker_reset_s) for p in providers}

    def call(self, *args):
        errors = []
        for p in self.providers:
            br = self.breakers[p.name]
            if not br.allow():
                errors.append(f"{p.name}: circuit open (recent repeated failures)")
                continue
            try:
                result = with_retry(
                    lambda p=p: run_with_timeout(lambda: getattr(p, self.method)(*args), self.s.timeout_s),
                    attempts=self.s.retries,
                )
                br.success()
                return p.name, result, errors
            except TickerNotFound as e:
                br.success()
                errors.append(f"{p.name}: {e}")
                raise AllProvidersFailed(errors)
            except Exception as e:  # noqa: BLE001
                br.failure()
                errors.append(f"{p.name}: {type(e).__name__}: {e}")
        raise AllProvidersFailed(errors)
