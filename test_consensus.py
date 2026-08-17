from core.consensus_engine import Signal, StrategyVote, evaluate_consensus

votes1 = [
    StrategyVote("ICT", Signal.LONG, 8),
    StrategyVote("SMC", Signal.LONG, 7),
    StrategyVote("Wyckoff", Signal.LONG, 9),
    StrategyVote("Price Action", Signal.LONG, 6),
]
r1 = evaluate_consensus(votes1)
print("Test 1:", r1.consensus, "|", r1.action.value, "| Score:", r1.weighted_score)

votes2 = [
    StrategyVote("ICT", Signal.LONG, 8),
    StrategyVote("SMC", Signal.LONG, 7),
    StrategyVote("Wyckoff", Signal.LONG, 9),
    StrategyVote("Price Action", Signal.SHORT, 5),
]
r2 = evaluate_consensus(votes2)
print("Test 2:", r2.consensus, "|", r2.action.value, "| Score:", r2.weighted_score)

votes3 = [
    StrategyVote("ICT", Signal.LONG, 8),
    StrategyVote("SMC", Signal.LONG, 7),
    StrategyVote("Wyckoff", Signal.SHORT, 6),
    StrategyVote("Price Action", Signal.SHORT, 5),
]
r3 = evaluate_consensus(votes3)
print("Test 3:", r3.consensus, "|", r3.action.value, "| Score:", r3.weighted_score)
