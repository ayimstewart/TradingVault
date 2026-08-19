import type { ChatMessage, ConsensusResult } from "@/types"

const DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

interface DeepSeekOptions {
  messages: ChatMessage[]
  consensus: ConsensusResult | null
  selectedTicker: string | null
}

function buildSystemPrompt(
  consensus: ConsensusResult | null,
  selectedTicker: string | null,
): string {
  const tickerLine = selectedTicker
    ? `Active watchlist ticker: ${selectedTicker}.`
    : "No watchlist ticker selected."

  const consensusLine = consensus
    ? `Latest consensus: ${consensus.consensus} (${consensus.action}). Long ratio ${(consensus.longRatio * 100).toFixed(0)}%. Weighted score ${consensus.weightedScore.toFixed(2)}.`
    : "No consensus evaluation has been run yet."

  return [
    "You are DeepSeek Reasoning inside TradingVault Pro.",
    "Provide concise, risk-aware trading analysis grounded in the consensus engine output.",
    "Never recommend a trade without mentioning alignment, conflicts, and capital preservation.",
    tickerLine,
    consensusLine,
  ].join(" ")
}

function buildLocalReasoning(
  userMessage: string,
  consensus: ConsensusResult | null,
  selectedTicker: string | null,
): string {
  const ticker = selectedTicker ?? "the watchlist"

  if (!consensus) {
    return [
      `You asked about ${ticker} before a consensus evaluation was run.`,
      "Configure ICT, SMC, Wyckoff, and Price Action votes, then click Evaluate Consensus.",
      "Once a label and action appear, I can reason about directional alignment and whether the setup meets your checklist.",
      `\nRegarding your question: ${userMessage}`,
    ].join(" ")
  }

  const alignment =
    consensus.consensus === "NO_TRADE"
      ? "Strategies are not aligned enough for a directional bias."
      : `Directional bias is ${consensus.consensus.replace("_", " ")} with action ${consensus.action}.`

  const scoreInterpretation =
    consensus.weightedScore > 3
      ? "Weighted score skews bullish."
      : consensus.weightedScore < -3
        ? "Weighted score skews bearish."
        : "Weighted score is neutral to mixed."

  return [
    `Analysis for ${ticker}:`,
    alignment,
    `Long participation: ${(consensus.longRatio * 100).toFixed(0)}%. ${scoreInterpretation}`,
    consensus.action === "EXECUTE"
      ? "Four-of-four agreement — highest conviction, but still confirm ATR(7) stop and weekly bias before execution."
      : consensus.action === "REVIEW"
        ? "Three-of-four agreement — review dissenting strategy and session risk before sizing."
        : "Agreement is weak or absent — capital preservation favors waiting for cleaner alignment.",
    `\nYour question: ${userMessage}`,
  ].join("\n\n")
}

export async function requestDeepSeekReply(
  options: DeepSeekOptions,
): Promise<string> {
  const apiKey = import.meta.env.VITE_DEEPSEEK_API_KEY as string | undefined

  if (!apiKey) {
    return buildLocalReasoning(
      options.messages.at(-1)?.content ?? "",
      options.consensus,
      options.selectedTicker,
    )
  }

  const payload = {
    model: "deepseek-chat",
    messages: [
      {
        role: "system",
        content: buildSystemPrompt(options.consensus, options.selectedTicker),
      },
      ...options.messages.map((message) => ({
        role: message.role,
        content: message.content,
      })),
    ],
    temperature: 0.4,
  }

  const response = await fetch(DEEPSEEK_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    return buildLocalReasoning(
      options.messages.at(-1)?.content ?? "",
      options.consensus,
      options.selectedTicker,
    )
  }

  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>
  }

  return (
    data.choices?.[0]?.message?.content ??
    buildLocalReasoning(
      options.messages.at(-1)?.content ?? "",
      options.consensus,
      options.selectedTicker,
    )
  )
}
