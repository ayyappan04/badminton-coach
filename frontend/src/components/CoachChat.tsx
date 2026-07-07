import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CoachAnswer } from "../types";

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
      setMessages((m) => [...m, { role: "coach", text: answer.answer, evidence: answer.evidence, confidence: answer.confidence }]);
      if (answer.suggested_questions?.length) setSuggestions(answer.suggested_questions);
    } catch {
      setMessages((m) => [...m, { role: "coach", text: "Something went wrong reaching your coaching data — try again in a moment." }]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  return (
    <div className="w-full max-w-xl mx-auto text-left">
      {messages.length > 0 && (
        <div className="space-y-3 mb-4 max-h-80 overflow-y-auto pr-1">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`rounded-xl px-3.5 py-2.5 text-sm max-w-[85%] ${
                  m.role === "user"
                    ? "bg-[var(--color-accent)] text-white"
                    : "bg-[var(--color-card)] border border-[var(--color-border)]"
                }`}
              >
                <p>{m.text}</p>
                {m.role === "coach" && m.evidence && m.evidence.length > 0 && (
                  <div className="mt-2 flex gap-2 flex-wrap">
                    {m.evidence.map((e, j) => (
                      <button
                        key={j}
                        onClick={() => navigate(`/dashboard?video=${e.video_id}&t=${e.timestamp_s}`)}
                        className="text-[10px] border border-[var(--color-accent)] text-[var(--color-accent)] rounded-full px-2 py-0.5 hover:bg-[var(--color-accent-soft)]"
                      >
                        ▶ Watch the moment ({formatTime(e.timestamp_s)})
                      </button>
                    ))}
                  </div>
                )}
                {m.role === "coach" && m.confidence != null && (
                  <p className="text-[10px] text-[var(--color-ink-soft)] mt-1.5">{Math.round(m.confidence * 100)}% confidence — based on your analyzed matches</p>
                )}
              </div>
            </div>
          ))}
          {busy && <p className="text-xs text-[var(--color-ink-soft)]">Coach is checking your match data…</p>}
        </div>
      )}

      <div className="flex gap-1.5 flex-wrap mb-3 justify-center">
        {suggestions.slice(0, 4).map((q) => (
          <button
            key={q}
            onClick={() => ask(q)}
            className="text-xs border border-[var(--color-border-strong)] text-[var(--color-ink-soft)] rounded-full px-3 py-1.5 hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition"
          >
            {q}
          </button>
        ))}
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask your coach about your game…"
          className="flex-1 border border-[var(--color-border)] rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:border-[var(--color-accent)]"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="bg-[var(--color-accent)] text-white rounded-lg px-4 text-sm font-medium disabled:opacity-40 hover:bg-[var(--color-accent-dark)]"
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
