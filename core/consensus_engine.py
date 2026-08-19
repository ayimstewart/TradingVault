"""Stateless consensus engine for multi-strategy trading vote evaluation.

Evaluates agreement across four discretionary strategy frameworks — ICT, SMC,
Wyckoff, and Price Action — and maps vote alignment to a consensus label,
recommended action, and weighted directional score.

This module uses only the Python standard library and is designed for
deterministic, side-effect-free unit testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, Iterable, Sequence

# ── Constants ────────────────────────────────────────────────────────────────

EXPECTED_STRATEGIES: Final[frozenset[str]] = frozenset(
    {"ICT", "SMC", "Wyckoff", "Price Action"}
)
"""Canonical strategy names required for a full consensus evaluation."""

VOTE_COUNT: Final[int] = 4
"""Number of strategy votes the engine expects."""

MIN_CONFIDENCE: Final[int] = 1
MAX_CONFIDENCE: Final[int] = 10

STRENGTH_STRONG: Final[str] = "STRONG"
STRENGTH_MODERATE: Final[str] = "MODERATE"
STRENGTH_WEAK: Final[str] = "WEAK"
CONSENSUS_NO_TRADE: Final[str] = "NO_TRADE"


# ── Enumerations ─────────────────────────────────────────────────────────────


class Signal(Enum):
    """Directional bias emitted by a single strategy."""

    LONG = 1
    SHORT = -1
    NEUTRAL = 0


class Action(Enum):
    """Recommended handling after consensus evaluation."""

    EXECUTE = "EXECUTE"
    REVIEW = "REVIEW"
    SKIP = "SKIP"


# Agreement count → (strength label, action). Populated after Action is defined.
_AGREEMENT_RULES: Final[dict[int, tuple[str, Action]]] = {
    4: (STRENGTH_STRONG, Action.EXECUTE),
    3: (STRENGTH_MODERATE, Action.REVIEW),
    2: (STRENGTH_WEAK, Action.SKIP),
}


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StrategyVote:
    """One strategy's vote on market direction.

    Attributes:
        strategy: Strategy identifier (e.g. ``"ICT"``, ``"SMC"``).
        signal: Directional signal from the strategy.
        confidence: Conviction level from 1 (low) to 10 (high).
    """

    strategy: str
    signal: Signal
    confidence: int

    def __post_init__(self) -> None:
        if not self.strategy.strip():
            raise ValueError("strategy must be a non-empty string")
        if not MIN_CONFIDENCE <= self.confidence <= MAX_CONFIDENCE:
            raise ValueError(
                f"confidence must be between {MIN_CONFIDENCE} and "
                f"{MAX_CONFIDENCE}, got {self.confidence}"
            )

    def to_dict(self) -> dict[str, object]:
        """Serialize this vote to a JSON-friendly dictionary."""
        return {
            "strategy": self.strategy,
            "signal": self.signal.name,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    """Outcome of evaluating strategy vote alignment.

    Attributes:
        consensus: Human-readable label such as ``"STRONG_LONG"`` or
            ``"NO_TRADE"``.
        action: Recommended next step for the trading workflow.
        long_ratio: Share of votes cast as LONG (0.0–1.0).
        short_ratio: Share of votes cast as SHORT (0.0–1.0).
        weighted_score: Directional score from -10.0 to +10.0 derived from
            signal polarity and confidence across all votes.
        votes: Serialized strategy votes included in the evaluation.
        timestamp: UTC ISO-8601 timestamp of evaluation.
    """

    consensus: str
    action: Action
    long_ratio: float
    short_ratio: float
    weighted_score: float
    votes: list[dict[str, object]]
    timestamp: str


# ── Validation helpers (unit-testable) ───────────────────────────────────────


def validate_votes(votes: Sequence[StrategyVote]) -> None:
    """Ensure *votes* satisfy structural constraints.

    Args:
        votes: Strategy votes to validate.

    Raises:
        ValueError: If vote count, duplicates, or strategy names are invalid.
    """
    if len(votes) != VOTE_COUNT:
        raise ValueError(f"expected exactly {VOTE_COUNT} votes, got {len(votes)}")

    strategies = [vote.strategy for vote in votes]
    if len(set(strategies)) != len(strategies):
        raise ValueError("duplicate strategy names are not allowed")

    unknown = set(strategies) - EXPECTED_STRATEGIES
    if unknown:
        raise ValueError(
            f"unexpected strategy name(s): {sorted(unknown)}; "
            f"expected one of {sorted(EXPECTED_STRATEGIES)}"
        )


def count_directions(
    votes: Iterable[StrategyVote],
) -> tuple[int, int, int]:
    """Count LONG, SHORT, and NEUTRAL votes.

    Args:
        votes: Votes to tally.

    Returns:
        A tuple ``(long_count, short_count, neutral_count)``.
    """
    long_count = short_count = neutral_count = 0
    for vote in votes:
        if vote.signal is Signal.LONG:
            long_count += 1
        elif vote.signal is Signal.SHORT:
            short_count += 1
        else:
            neutral_count += 1
    return long_count, short_count, neutral_count


def compute_ratios(long_count: int, short_count: int) -> tuple[float, float]:
    """Compute directional vote ratios against the fixed vote pool size.

    Args:
        long_count: Number of LONG votes.
        short_count: Number of SHORT votes.

    Returns:
        ``(long_ratio, short_ratio)`` each in ``[0.0, 1.0]``.
    """
    return long_count / VOTE_COUNT, short_count / VOTE_COUNT


def compute_weighted_score(votes: Sequence[StrategyVote]) -> float:
    """Compute mean directional score from signal polarity and confidence.

    Each vote contributes ``signal.value * confidence``. The mean is taken
    over all votes, yielding a range of ``[-10.0, +10.0]`` when confidence
    is within ``[1, 10]``.

    Args:
        votes: Votes to score.

    Returns:
        Weighted score in ``[-10.0, +10.0]`` for valid confidence inputs.
    """
    if not votes:
        return 0.0
    total = sum(vote.signal.value * vote.confidence for vote in votes)
    return total / len(votes)


def resolve_dominant_direction(
    long_count: int,
    short_count: int,
) -> tuple[int, str | None]:
    """Pick the winning direction and its agreement count.

    Args:
        long_count: Number of LONG votes.
        short_count: Number of SHORT votes.

    Returns:
        ``(agreement_count, direction)`` where *direction* is ``"LONG"``,
        ``"SHORT"``, or ``None`` when there is no unique dominant direction
        (tie or zero directional votes).
    """
    if long_count > short_count:
        return long_count, "LONG"
    if short_count > long_count:
        return short_count, "SHORT"
    return max(long_count, short_count), None


def build_consensus_label(agreement_count: int, direction: str | None) -> str:
    """Map agreement count and direction to a consensus label.

    Args:
        agreement_count: Number of votes sharing the dominant direction.
        direction: ``"LONG"``, ``"SHORT"``, or ``None`` when undecided.

    Returns:
        Consensus string such as ``"STRONG_LONG"`` or ``"NO_TRADE"``.
    """
    if direction is None or agreement_count <= 1:
        return CONSENSUS_NO_TRADE

    strength, _ = _AGREEMENT_RULES.get(
        agreement_count,
        (STRENGTH_WEAK, Action.SKIP),
    )
    return f"{strength}_{direction}"


def resolve_action(agreement_count: int, direction: str | None) -> Action:
    """Map agreement count and direction to a recommended action.

    Args:
        agreement_count: Number of votes sharing the dominant direction.
        direction: ``"LONG"``, ``"SHORT"``, or ``None`` when undecided.

    Returns:
        ``Action.EXECUTE``, ``Action.REVIEW``, or ``Action.SKIP``.
    """
    if direction is None or agreement_count <= 1:
        return Action.SKIP
    return _AGREEMENT_RULES.get(agreement_count, (STRENGTH_WEAK, Action.SKIP))[1]


# ── Public API ───────────────────────────────────────────────────────────────


def evaluate_consensus(
    votes: Sequence[StrategyVote],
    *,
    timestamp: datetime | None = None,
) -> ConsensusResult:
    """Evaluate multi-strategy vote alignment and return a consensus result.

    Consensus rules (directional votes only; NEUTRAL does not count toward
    agreement):

    - 4/4 same direction → ``STRONG_{LONG|SHORT}`` → ``Action.EXECUTE``
    - 3/4 same direction → ``MODERATE_{LONG|SHORT}`` → ``Action.REVIEW``
    - 2/4 same direction → ``WEAK_{LONG|SHORT}`` → ``Action.SKIP``
    - 1/4, tie, or no directional majority → ``NO_TRADE`` → ``Action.SKIP``

    Args:
        votes: Exactly four :class:`StrategyVote` instances, one per expected
            strategy in :data:`EXPECTED_STRATEGIES`.
        timestamp: Optional UTC timestamp for the result; defaults to now.

    Returns:
        A :class:`ConsensusResult` with consensus label, action, ratios,
        weighted score, serialized votes, and ISO-8601 timestamp.

    Raises:
        ValueError: If *votes* fail :func:`validate_votes` checks.

    Example:
        >>> votes = [
        ...     StrategyVote("ICT", Signal.LONG, 8),
        ...     StrategyVote("SMC", Signal.LONG, 7),
        ...     StrategyVote("Wyckoff", Signal.LONG, 9),
        ...     StrategyVote("Price Action", Signal.LONG, 6),
        ... ]
        >>> result = evaluate_consensus(votes)
        >>> result.consensus
        'STRONG_LONG'
        >>> result.action
        <Action.EXECUTE: 'EXECUTE'>
    """
    validate_votes(votes)

    long_count, short_count, _neutral_count = count_directions(votes)
    long_ratio, short_ratio = compute_ratios(long_count, short_count)
    weighted_score = compute_weighted_score(votes)

    agreement_count, direction = resolve_dominant_direction(long_count, short_count)
    consensus = build_consensus_label(agreement_count, direction)
    action = resolve_action(agreement_count, direction)

    ts = timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    serialized_votes = [vote.to_dict() for vote in votes]

    return ConsensusResult(
        consensus=consensus,
        action=action,
        long_ratio=long_ratio,
        short_ratio=short_ratio,
        weighted_score=weighted_score,
        votes=serialized_votes,
        timestamp=ts.isoformat(),
    )


__all__ = [
    "EXPECTED_STRATEGIES",
    "VOTE_COUNT",
    "Action",
    "ConsensusResult",
    "Signal",
    "StrategyVote",
    "build_consensus_label",
    "compute_ratios",
    "compute_weighted_score",
    "count_directions",
    "evaluate_consensus",
    "resolve_action",
    "resolve_dominant_direction",
    "validate_votes",
]
