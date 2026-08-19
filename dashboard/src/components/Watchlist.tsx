import { WATCHLIST_TICKERS, type WatchlistTicker } from "@/types"
import { cn } from "@/lib/utils"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

interface WatchlistProps {
  selectedTicker: WatchlistTicker | null
  onSelectTicker: (ticker: WatchlistTicker) => void
}

export function Watchlist({ selectedTicker, onSelectTicker }: WatchlistProps) {
  return (
    <Card className="h-full border-gray-800 bg-gray-900 text-white shadow-none">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold tracking-tight">
          Watchlist
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {WATCHLIST_TICKERS.map((ticker) => {
          const isActive = selectedTicker === ticker

          return (
            <button
              key={ticker}
              type="button"
              onClick={() => onSelectTicker(ticker)}
              className={cn(
                "flex w-full items-center justify-between rounded-lg border border-gray-800 px-4 py-3 text-left transition-colors",
                "hover:border-gray-700 hover:bg-gray-800/80",
                isActive && "border-emerald-800/60 bg-gray-800",
              )}
            >
              <span className="font-medium tracking-wide">{ticker}</span>
              <span className="flex items-center gap-2 text-xs text-gray-400">
                {isActive ? "Active" : "Idle"}
                <span
                  className={cn(
                    "h-2.5 w-2.5 rounded-full",
                    isActive ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-gray-600",
                  )}
                  aria-hidden="true"
                />
              </span>
            </button>
          )
        })}
      </CardContent>
    </Card>
  )
}
