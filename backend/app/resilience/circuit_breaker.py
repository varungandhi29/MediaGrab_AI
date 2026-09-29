import time
import asyncio
from enum import Enum
from collections import deque
from typing import Dict, Tuple, List, Any, Optional

from ..config import settings
from .error_classifier import FailureCategory


class CircuitState(str, Enum):
    CLOSED = "CLOSED"         # Normal operation: requests pass through
    OPEN = "OPEN"             # Tripped: requests are skipped, jumps to next fallback
    HALF_OPEN = "HALF_OPEN"   # Cooldown expired: trial request testing recovery


class TierCircuitEntry:
    def __init__(
        self,
        tier: str,
        domain: str,
        window_size: int = 20,
        min_samples: int = 5,
        failure_threshold: float = 0.80,
        cooldown_seconds: int = 1800,
    ):
        self.tier = tier
        self.domain = domain
        self.window_size = window_size
        self.min_samples = min_samples
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self.state: CircuitState = CircuitState.CLOSED
        self.history: deque = deque(maxlen=window_size)  # Stores tuples of (timestamp, success: bool, category: str)
        self.last_tripped_at: Optional[float] = None
        self.last_state_change: float = time.time()
        self.trip_count: int = 0
        self.trial_in_progress: bool = False

    def can_execute(self, now: Optional[float] = None) -> bool:
        """Determines if a request for this tier & domain is allowed to execute."""
        now = now or time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown period has elapsed
            if self.last_tripped_at and (now - self.last_tripped_at) >= self.cooldown_seconds:
                # Transition to HALF_OPEN to permit a single trial request
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                self.trial_in_progress = True
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Allow trial request if not already occupied
            if not self.trial_in_progress:
                self.trial_in_progress = True
                return True
            return False

        return True

    def record_result(self, success: bool, category: Optional[FailureCategory] = None, now: Optional[float] = None):
        """Records an execution outcome and manages circuit state transitions."""
        now = now or time.time()
        cat_str = category.value if category else ("SUCCESS" if success else "UNKNOWN")
        self.history.append((now, success, cat_str))

        if self.state == CircuitState.HALF_OPEN:
            self.trial_in_progress = False
            if success:
                # Trial request succeeded: Recovery confirmed, close circuit
                self.state = CircuitState.CLOSED
                self.last_state_change = now
            else:
                # Trial request failed: Re-open circuit for another cooldown
                self.state = CircuitState.OPEN
                self.last_tripped_at = now
                self.last_state_change = now
                self.trip_count += 1
            return

        if self.state == CircuitState.CLOSED:
            if not success:
                # Evaluate rolling failure rate
                total = len(self.history)
                if total >= self.min_samples:
                    failures = sum(1 for _, s, _ in self.history if not s)
                    rate = failures / total
                    if rate >= self.failure_threshold:
                        # Trip circuit to OPEN
                        self.state = CircuitState.OPEN
                        self.last_tripped_at = now
                        self.last_state_change = now
                        self.trip_count += 1

    def get_failure_rate(self) -> float:
        if not self.history:
            return 0.0
        failures = sum(1 for _, s, _ in self.history if not s)
        return round(failures / len(self.history), 3)

    def get_cooldown_remaining(self, now: Optional[float] = None) -> float:
        if self.state != CircuitState.OPEN or not self.last_tripped_at:
            return 0.0
        now = now or time.time()
        elapsed = now - self.last_tripped_at
        return max(0.0, round(self.cooldown_seconds - elapsed, 1))

    def get_dominant_category(self) -> str:
        failed_cats = [c for _, s, c in self.history if not s and c != "SUCCESS"]
        if not failed_cats:
            return "NONE"
        return max(set(failed_cats), key=failed_cats.count)

    def reset(self):
        self.state = CircuitState.CLOSED
        self.history.clear()
        self.last_tripped_at = None
        self.last_state_change = time.time()
        self.trial_in_progress = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "domain": self.domain,
            "state": self.state.value,
            "failure_rate": self.get_failure_rate(),
            "sample_count": len(self.history),
            "trip_count": self.trip_count,
            "cooldown_remaining_seconds": self.get_cooldown_remaining(),
            "dominant_failure_category": self.get_dominant_category(),
            "last_tripped_at": self.last_tripped_at,
        }


class CircuitBreakerRegistry:
    """
    Registry managing multi-tier per-domain circuit breakers.
    Tracks failure rates for (yt-dlp, direct, static_scrape, headless_browser) across domains.
    """
    def __init__(self):
        self._circuits: Dict[Tuple[str, str], TierCircuitEntry] = {}
        self._lock = asyncio.Lock()

    def _get_or_create(self, tier: str, domain: str) -> TierCircuitEntry:
        key = (tier.lower(), domain.lower())
        if key not in self._circuits:
            self._circuits[key] = TierCircuitEntry(
                tier=tier,
                domain=domain,
                window_size=settings.CIRCUIT_BREAKER_WINDOW_SIZE,
                min_samples=settings.CIRCUIT_BREAKER_MIN_SAMPLES,
                failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                cooldown_seconds=settings.CIRCUIT_BREAKER_COOLDOWN_SECONDS,
            )
        return self._circuits[key]

    async def can_execute(self, tier: str, domain: str) -> bool:
        async with self._lock:
            entry = self._get_or_create(tier, domain)
            return entry.can_execute()

    async def record_result(
        self,
        tier: str,
        domain: str,
        success: bool,
        category: Optional[FailureCategory] = None
    ):
        async with self._lock:
            entry = self._get_or_create(tier, domain)
            entry.record_result(success=success, category=category)

    async def get_circuit_status(self, tier: str, domain: str) -> Dict[str, Any]:
        async with self._lock:
            entry = self._get_or_create(tier, domain)
            return entry.to_dict()

    async def get_all_circuits(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [entry.to_dict() for entry in self._circuits.values()]

    async def get_open_circuits(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                entry.to_dict()
                for entry in self._circuits.values()
                if entry.state == CircuitState.OPEN
            ]

    async def reset_circuit(self, tier: str, domain: str) -> bool:
        async with self._lock:
            key = (tier.lower(), domain.lower())
            if key in self._circuits:
                self._circuits[key].reset()
                return True
            return False

    async def reset_all(self) -> int:
        async with self._lock:
            count = len(self._circuits)
            for c in self._circuits.values():
                c.reset()
            return count


circuit_breaker_registry = CircuitBreakerRegistry()
