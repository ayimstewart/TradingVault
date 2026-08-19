import { useEffect, useRef, useState, type FormEvent } from "react"
import { requestDeepSeekReply } from "@/lib/deepseek"
import { cn } from "@/lib/utils"
import type { ChatMessage, ConsensusResult } from "@/types"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"

const STORAGE_KEY = "tradingvault-pro-chat"

interface ChatPanelProps {
  consensus: ConsensusResult | null
  selectedTicker: string | null
}

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as ChatMessage[]) : []
  } catch {
    return []
  }
}

function createMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: new Date().toISOString(),
  }
}

export function ChatPanel({ consensus, selectedTicker }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadStoredMessages)
  const [input, setInput] = useState("")
  const [isSending, setIsSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
  }, [messages])

  useEffect(() => {
    const container = scrollRef.current
    if (container) {
      container.scrollTop = container.scrollHeight
    }
  }, [messages, isSending])

  async function handleSend(event: FormEvent) {
    event.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || isSending) return

    const userMessage = createMessage("user", trimmed)
    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setInput("")
    setIsSending(true)

    try {
      const reply = await requestDeepSeekReply({
        messages: nextMessages,
        consensus,
        selectedTicker,
      })
      setMessages((current) => [...current, createMessage("assistant", reply)])
    } catch {
      setMessages((current) => [
        ...current,
        createMessage(
          "assistant",
          "Unable to reach DeepSeek right now. Check your network or API key and try again.",
        ),
      ])
    } finally {
      setIsSending(false)
    }
  }

  return (
    <Card className="flex h-full min-h-[420px] flex-col border-gray-800 bg-gray-900 text-white shadow-none lg:min-h-0">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold tracking-tight">
          DeepSeek Reasoning
        </CardTitle>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-4">
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950/60 p-4"
        >
          {messages.length === 0 ? (
            <p className="text-sm text-gray-500">
              Ask DeepSeek about this consensus...
            </p>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "flex",
                  message.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed",
                    message.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-100",
                  )}
                >
                  {message.content}
                </div>
              </div>
            ))
          )}
          {isSending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-gray-800 px-4 py-2 text-sm text-gray-400">
                Reasoning...
              </div>
            </div>
          )}
        </div>

        <form onSubmit={handleSend} className="flex gap-2">
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask DeepSeek about this consensus..."
            className="border-gray-800 bg-gray-950 text-white placeholder:text-gray-500"
            disabled={isSending}
          />
          <Button
            type="submit"
            disabled={isSending || input.trim().length === 0}
            className="bg-blue-600 text-white hover:bg-blue-500"
          >
            Send
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
