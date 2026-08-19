import type { TradeLogEntry } from "@/types"

const TRADES_API = "/api/trades"

export async function fetchTradeLog(): Promise<TradeLogEntry[]> {
  try {
    const response = await fetch(TRADES_API, {
      headers: { Accept: "application/json" },
    })

    if (!response.ok) {
      return []
    }

    const data: unknown = await response.json()

    if (!Array.isArray(data)) {
      return []
    }

    return data.filter(isTradeLogEntry)
  } catch {
    return []
  }
}

function isTradeLogEntry(value: unknown): value is TradeLogEntry {
  if (typeof value !== "object" || value === null) return false
  const entry = value as Record<string, unknown>
  return (
    typeof entry.date === "string" &&
    typeof entry.ticker === "string" &&
    typeof entry.consensus === "string" &&
    (entry.action === "EXECUTE" ||
      entry.action === "REVIEW" ||
      entry.action === "SKIP")
  )
}
