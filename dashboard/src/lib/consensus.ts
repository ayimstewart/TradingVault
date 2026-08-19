import type {
  Action,
  ConsensusResult,
  Signal,
  StrategyVote,
} from "@/types"

const VOTE_COUNT = 4

const SIGNAL_VALUE: Record<Signal, number> = {
  LONG: 1,
  SHORT: -1,
  NEUTRAL: 0,
}

function countDirections(votes: StrategyVote[]) {
  let longCount = 0
  let shortCount = 0
  let neutralCount = 0

  for (const vote of votes) {
    if (vote.signal === "LONG") longCount += 1
    else if (vote.signal === "SHORT") shortCount += 1
    else neutralCount += 1
  }

  return { longCount, shortCount, neutralCount }
}

function resolveDominantDirection(longCount: number, shortCount: number) {
  if (longCount > shortCount) {
    return { agreementCount: longCount, direction: "LONG" as const }
  }
  if (shortCount > longCount) {
    return { agreementCount: shortCount, direction: "SHORT" as const }
  }
  return {
    agreementCount: Math.max(longCount, shortCount),
    direction: null,
  }
}

function buildConsensusLabel(
  agreementCount: number,
  direction: "LONG" | "SHORT" | null,
): string {
  if (direction === null || agreementCount <= 1) {
    return "NO_TRADE"
  }
  if (agreementCount === 4) return `STRONG_${direction}`
  if (agreementCount === 3) return `MODERATE_${direction}`
  if (agreementCount === 2) return `WEAK_${direction}`
  return "NO_TRADE"
}

function resolveAction(
  agreementCount: number,
  direction: "LONG" | "SHORT" | null,
): Action {
  if (direction === null || agreementCount <= 1) return "SKIP"
  if (agreementCount === 4) return "EXECUTE"
  if (agreementCount === 3) return "REVIEW"
  return "SKIP"
}

function computeWeightedScore(votes: StrategyVote[]): number {
  if (votes.length === 0) return 0
  const total = votes.reduce(
    (sum, vote) => sum + SIGNAL_VALUE[vote.signal] * vote.confidence,
    0,
  )
  return total / votes.length
}

export function evaluateConsensus(votes: StrategyVote[]): ConsensusResult {
  const { longCount, shortCount } = countDirections(votes)
  const { agreementCount, direction } = resolveDominantDirection(
    longCount,
    shortCount,
  )

  return {
    consensus: buildConsensusLabel(agreementCount, direction),
    action: resolveAction(agreementCount, direction),
    longRatio: longCount / VOTE_COUNT,
    shortRatio: shortCount / VOTE_COUNT,
    weightedScore: computeWeightedScore(votes),
    votes: votes.map((vote) => ({
      strategy: vote.strategy,
      signal: vote.signal,
      confidence: vote.confidence,
    })),
    timestamp: new Date().toISOString(),
  }
}
