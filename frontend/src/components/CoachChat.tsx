import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CoachAnswer } from "../types";
import { Button, Surface, formatTimestamp } from "../ui";

interface ChatMessage {
  role: "user" | "coach";
  text: string;
  evidence?: CoachAnswer["evidence"];
  confidence?: number | null;
}

const STARTER_QUESTIONS = [
  "Why am I losing points at the net?",
  "What should I train this week?",
  "Which shot should I use more often?",
  "How is my progress trending?",
];

export function CoachChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>(STARTER_QUESTIONS);
  const navigate = useNavigate();

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    setBusy(true);
    try {
      const answer = await api.post<CoachAnswer>("/coach/ask", { question });
      setMessages((m) => [
        ...m,
        { role: "coach", text: answer.answer, evidence: answer.evidence, confidence: answer.confidence },
      ]);
      if (answer.suggested_questions?.length) setSuggestions(answer.suggested_questions);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "coach", text: "I couldn't reach your coaching data just then — please try again." },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  return (
    <Surface padded={false} className="overflow-hidden">
      {messages.length > 0 && (
        <div
          className="max-h-80 overflow-y-auto p-4 space-y-3 border-b"
          style={{ borderColor: "var(--separator)" }}
          aria-live="polite"
        >
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className="rounded-[var(--radius-md)] px-3.5 py-2.5 text-[14px] max-w-[85%]"
                style={
                  m.role === "user"
                    ? { background: "var(--accent)", color: "#fff" }
                    : { background: "var(--surface-raised)", color: "var(--text-primary)" }
                }
              >
                <p className="whitespace-pre-line leading-snug">{m.text}</p>

                {m.role === "coach" && !!m.evidence?.length && (
                  <div className="mt-2.5 flex gap-1.5 flex-wrap">
                    {m.evidence.map((e, j) => (
                      <button
                        key={j}
                        onClick={() => navigate(`/dashboard?video=${e.video_id}&t=${e.timestamp_s}`)}
                        className="tnum h-7 px-2.5 rounded-[var(--radius-sm)] text-[12px] font-medium transition-colors hover:brightness-125"
                        style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                      >
                        ▶ {formatTimestamp(e.timestamp_s)}
                      </button>
                    ))}
                  </div>
                )}

                {m.role === "coach" && m.confidence != null && (
                  <p className="text-[11.5px] mt-2" style={{ color: "var(--text-tertiary)" }}>
                    {Math.round(m.confidence * 100)}% confidence — from your analyzed matches
                  </p>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
              Checking your match data…
            </p>
          )}
        </div>
      )}

      <div className="p-4">
        <div className="flex gap-1.5 flex-wrap mb-3">
          {suggestions.slice(0, 4).map((q) => (
            <button
              key={q}
              onClick={() => ask(q)}
              className="text-[12.5px] rounded-[var(--radius-full)] px-3 h-8 border transition-colors hover:bg-[var(--surface-hover)]"
              style={{ borderColor: "var(--separator-strong)", color: "var(--text-secondary)" }}
            >
              {q}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your game…"
            aria-label="Ask your coach a question"
            className="flex-1 min-w-0"
          />
          <Button type="submit" variant="primary" disabled={busy || !input.trim()}>
            Ask
          </Button>
        </form>
      </div>
    </Surface>
  );
}
