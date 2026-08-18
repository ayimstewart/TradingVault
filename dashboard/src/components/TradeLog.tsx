import { useEffect, useState } from "react"
import { fetchTradeLog } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Action, TradeLogEntry } from "@/types"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

function actionBadgeClass(action: Action) {
  switch (action) {
    case "EXECUTE":
      return "border-emerald-700 bg-emerald-950 text-emerald-300 hover:bg-emerald-950"
    case "REVIEW":
      return "border-amber-700 bg-amber-950 text-amber-300 hover:bg-amber-950"
    case "SKIP":
      return "border-red-700 bg-red-950 text-red-300 hover:bg-red-950"
  }
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function TradeLog() {
  const [entries, setEntries] = useState<TradeLogEntry[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadTrades() {
      setIsLoading(true)
      setError(null)

      try {
        const data = await fetchTradeLog()
        if (!cancelled) {
          setEntries(data)
        }
      } catch {
        if (!cancelled) {
          setError("Unable to load trade log from API.")
          setEntries([])
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadTrades()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Card className="border-gray-800 bg-gray-900 text-white shadow-none">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold tracking-tight">
          Recent Decisions
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-gray-500">Loading trade log...</p>
        ) : error ? (
          <p className="text-sm text-red-400">{error}</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-gray-500">No trades logged yet</p>
        ) : (
          <div className="space-y-3">
            {entries.map((entry, index) => (
              <div
                key={`${entry.date}-${entry.ticker}-${index}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-800 bg-gray-950/60 px-4 py-3"
              >
                <div className="space-y-1">
                  <p className="text-sm text-gray-400">{formatDate(entry.date)}</p>
                  <p className="font-medium text-white">
                    {entry.ticker}{" "}
                    <span className="text-gray-400">·</span>{" "}
                    {entry.consensus.replace(/_/g, " ")}
                  </p>
                </div>
                <Badge className={cn("text-xs", actionBadgeClass(entry.action))}>
                  {entry.action}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
