import { useState } from "react"
import { ConsensusPanel } from "@/components/ConsensusPanel"
import { ChatPanel } from "@/components/ChatPanel"
import { TradeLog } from "@/components/TradeLog"
import { Watchlist } from "@/components/Watchlist"
import type { ConsensusResult, WatchlistTicker } from "@/types"

function App() {
  const [selectedTicker, setSelectedTicker] = useState<WatchlistTicker>("BTC")
  const [consensus, setConsensus] = useState<ConsensusResult | null>(null)

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col gap-4 p-4 lg:p-6">
        <header className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-900 px-4 py-3">
          <div className="flex items-center gap-3">
            <span
              className="h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.9)]"
              aria-hidden="true"
            />
            <h1 className="text-xl font-bold tracking-tight">TradingVault Pro</h1>
          </div>
          <p className="text-sm text-gray-400">Consensus · Reasoning · Decisions</p>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_minmax(0,1.4fr)]">
          <Watchlist
            selectedTicker={selectedTicker}
            onSelectTicker={setSelectedTicker}
          />
          <ConsensusPanel onEvaluate={setConsensus} />
          <ChatPanel consensus={consensus} selectedTicker={selectedTicker} />
        </div>

        <TradeLog />
      </div>
    </div>
  )
}

export default App
