import { useMemo, useState } from "react"
import { evaluateConsensus } from "@/lib/consensus"
import { cn } from "@/lib/utils"
import {
  EXPECTED_STRATEGIES,
  type ConsensusResult,
  type Signal,
  type StrategyName,
  type StrategyVote,
} from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"

interface StrategyState {
  signal: Signal
  confidence: number
}

const DEFAULT_STATE: Record<StrategyName, StrategyState> = {
  ICT: { signal: "NEUTRAL", confidence: 5 },
  SMC: { signal: "NEUTRAL", confidence: 5 },
  Wyckoff: { signal: "NEUTRAL", confidence: 5 },
  "Price Action": { signal: "NEUTRAL", confidence: 5 },
}

interface ConsensusPanelProps {
  onEvaluate?: (result: ConsensusResult) => void
}

function actionBadgeClass(action: ConsensusResult["action"]) {
  switch (action) {
    case "EXECUTE":
      return "border-emerald-700 bg-emerald-950 text-emerald-300 hover:bg-emerald-950"
    case "REVIEW":
      return "border-amber-700 bg-amber-950 text-amber-300 hover:bg-amber-950"
    case "SKIP":
      return "border-red-700 bg-red-950 text-red-300 hover:bg-red-950"
  }
}

export function ConsensusPanel({ onEvaluate }: ConsensusPanelProps) {
  const [strategyState, setStrategyState] =
    useState<Record<StrategyName, StrategyState>>(DEFAULT_STATE)
  const [result, setResult] = useState<ConsensusResult | null>(null)

  const votes = useMemo<StrategyVote[]>(
    () =>
      EXPECTED_STRATEGIES.map((strategy) => ({
        strategy,
        signal: strategyState[strategy].signal,
        confidence: strategyState[strategy].confidence,
      })),
    [strategyState],
  )

  function updateStrategy(
    strategy: StrategyName,
    patch: Partial<StrategyState>,
  ) {
    setStrategyState((current) => ({
      ...current,
      [strategy]: { ...current[strategy], ...patch },
    }))
  }

  function handleEvaluate() {
    const evaluation = evaluateConsensus(votes)
    setResult(evaluation)
    onEvaluate?.(evaluation)
  }

  function handleReset() {
    setResult(null)
    setStrategyState(DEFAULT_STATE)
  }

  return (
    <Card className="h-full border-gray-800 bg-gray-900 text-white shadow-none">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold tracking-tight">
          Consensus Engine
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {EXPECTED_STRATEGIES.map((strategy) => {
            const state = strategyState[strategy]

            return (
              <div
                key={strategy}
                className="space-y-3 rounded-lg border border-gray-800 bg-gray-950/60 p-4"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-100">
                    {strategy}
                  </h3>
                  <span className="text-sm font-medium text-emerald-400">
                    {state.confidence}
                  </span>
                </div>

                <div className="space-y-2">
                  <label className="text-xs uppercase tracking-wide text-gray-500">
                    Signal
                  </label>
                  <Select
                    value={state.signal}
                    onValueChange={(value: Signal) =>
                      updateStrategy(strategy, { signal: value })
                    }
                  >
                    <SelectTrigger className="border-gray-800 bg-gray-900 text-white">
                      <SelectValue placeholder="Select signal" />
                    </SelectTrigger>
                    <SelectContent className="border-gray-800 bg-gray-900 text-white">
                      <SelectItem value="LONG">LONG</SelectItem>
                      <SelectItem value="SHORT">SHORT</SelectItem>
                      <SelectItem value="NEUTRAL">NEUTRAL</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <label className="text-xs uppercase tracking-wide text-gray-500">
                    Confidence
                  </label>
                  <Slider
                    min={1}
                    max={10}
                    step={1}
                    value={[state.confidence]}
                    onValueChange={(value) =>
                      updateStrategy(strategy, { confidence: value[0] ?? 1 })
                    }
                    className="py-2"
                  />
                </div>
              </div>
            )
          })}
        </div>

        <Button
          type="button"
          className="w-full bg-emerald-600 text-white hover:bg-emerald-500"
          size="lg"
          onClick={handleEvaluate}
        >
          Evaluate Consensus
        </Button>

        {result && (
          <div className="space-y-4 rounded-lg border border-gray-800 bg-gray-950/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-2xl font-bold tracking-tight text-white">
                {result.consensus.replace(/_/g, " ")}
              </p>
              <Badge className={cn("px-3 py-1 text-xs", actionBadgeClass(result.action))}>
                {result.action}
              </Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border border-gray-800 bg-gray-900 px-3 py-2">
                <p className="text-xs uppercase tracking-wide text-gray-500">
                  Long Ratio
                </p>
                <p className="text-lg font-semibold text-emerald-400">
                  {(result.longRatio * 100).toFixed(0)}%
                </p>
              </div>
              <div className="rounded-md border border-gray-800 bg-gray-900 px-3 py-2">
                <p className="text-xs uppercase tracking-wide text-gray-500">
                  Weighted Score
                </p>
                <p className="text-lg font-semibold text-white">
                  {result.weightedScore.toFixed(2)}
                </p>
              </div>
            </div>

            <Button
              type="button"
              variant="outline"
              className="w-full border-gray-700 bg-transparent text-gray-200 hover:bg-gray-800 hover:text-white"
              onClick={handleReset}
            >
              Reset
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
