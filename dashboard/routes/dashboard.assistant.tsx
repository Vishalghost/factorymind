import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { generateClient } from "aws-amplify/api";
import { Card } from "./dashboard.index";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send, Sparkles } from "lucide-react";
import { chatWithAssistantMutation } from "@/lib/graphql/assistant";

export const Route = createFileRoute("/dashboard/assistant")({ component: Assistant });

const SUGGESTIONS = [
  "What machines need attention right now?",
  "Top 3 risks in the next 24h",
  "How is the plant's energy efficiency?",
  "Summarise today's plant state in 4 bullets",
];

type Msg = { role: "user" | "ai"; text: string };

type ChatResponse = {
  session_id: string;
  answer?: string;
  error?: string;
  model_id?: string;
  context_used?: boolean;
};

function Assistant() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "ai",
      text: "Hi — I'm the FactoryMind GenAI Assistant, hosted on Bedrock AgentCore Runtime (Claude 3.5 Haiku). I have read access to live machine state. Ask me about the plant.",
    },
  ]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const sessionId = useRef<string>(crypto.randomUUID?.() ?? `sess-${Date.now()}`);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const clientRef = useRef(generateClient());

  // Keep the conversation pinned to the latest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending]);

  async function callBackend(text: string): Promise<string> {
    // Claude format: roles must be 'user' or 'assistant' (we map our local 'ai').
    const history = messages.slice(-6).map((m) => ({
      role: m.role === "ai" ? "assistant" : "user",
      content: m.text,
    }));

    const result = await clientRef.current.graphql({
      query: chatWithAssistantMutation,
      variables: {
        input: {
          message: text,
          session_id: sessionId.current,
          history,
        },
      },
    });

    // Amplify v6 GraphQL responses are loosely typed in TS — pull the data shape
    // out manually rather than fight the union type.
    const data = (result as unknown as { data: { chatWithAssistant: ChatResponse } }).data;
    const resp = data.chatWithAssistant;
    if (!resp) throw new Error("empty AppSync response");
    if (resp.error) throw new Error(resp.error);
    return resp.answer ?? "(no answer)";
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setInput("");
    setPending(true);
    try {
      const reply = await callBackend(trimmed);
      setMessages((m) => [...m, { role: "ai", text: reply }]);
    } catch (e) {
      const err = e as Error & { errors?: Array<{ message: string }> };
      const msg = err.errors?.[0]?.message ?? err.message ?? "request failed";
      setMessages((m) => [...m, { role: "ai", text: `⚠️ ${msg}` }]);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">
            GenAI · Bedrock AgentCore Runtime · Claude 3.5 Haiku
          </p>
          <h2 className="mt-1 font-display text-3xl font-bold">Natural-language operations</h2>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-success/15 px-2.5 py-1 text-xs font-medium text-success">
          <span className="h-1.5 w-1.5 rounded-full bg-current pulse-dot" />
          Live (AgentCore)
        </span>
      </div>

      <Card title="Conversation">
        <div ref={scrollRef} className="space-y-3 max-h-[420px] overflow-y-auto pr-2">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
              {m.role === "ai" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Sparkles className="h-4 w-4" />
                </div>
              )}
              <div
                className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm ${
                  m.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"
                }`}
              >
                {m.text}
              </div>
            </div>
          ))}
          {pending && (
            <div className="flex gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="rounded-2xl bg-secondary px-4 py-2.5 text-sm text-muted-foreground">
                Thinking…
              </div>
            </div>
          )}
        </div>
        <form
          onSubmit={(e) => { e.preventDefault(); send(input); }}
          className="mt-4 flex gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about machines, defects, energy…"
            disabled={pending}
          />
          <Button type="submit" disabled={pending || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={pending}
              className="rounded-full border border-border bg-card px-3 py-1 text-xs hover:border-primary/40 disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
