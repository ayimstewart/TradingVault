export type Signal = "LONG" | "SHORT" | "NEUTRAL"

export type Action = "EXECUTE" | "REVIEW" | "SKIP"

export type StrategyName = "ICT" | "SMC" | "Wyckoff" | "Price Action"

export const EXPECTED_STRATEGIES: StrategyName[] = [
  "ICT",
  "SMC",
  "Wyckoff",
  "Price Action",
]

export const WATCHLIST_TICKERS = [
  "BTC",
  "ETH",
  "SOL",
  "XRP",
  "LINK",
  "PEPE",
] as const

export type WatchlistTicker = (typeof WATCHLIST_TICKERS)[number]

export interface StrategyVote {
  strategy: StrategyName
  signal: Signal
  confidence: number
}

export interface ConsensusResult {
  consensus: string
  action: Action
  longRatio: number
  shortRatio: number
  weightedScore: number
  votes: Array<{
    strategy: string
    signal: Signal
    confidence: number
  }>
  timestamp: string
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: string
}

export interface TradeLogEntry {
  date: string
  ticker: string
  consensus: string
  action: Action
}
