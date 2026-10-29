import { AlertTriangle, BadgeCheck, Info, Loader2, SendHorizonal, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { EvidenceView } from "../components/EvidenceView";
import { PageHeader } from "../components/Layout";
import { Badge, Button, cx } from "../components/ui";
import { useAsync } from "../lib/useAsync";
export const EXAMPLES = [
  "شكد ربحت هذا الأسبوع؟",
  "شكد مبيعاتي اليوم؟",
  "منو بعده ما دايفعلي؟",
  "شكد ديون الزبائن عليه؟",
  "منو أكثر زبون يشتري مني؟",
  "قارنلي مبيعات هذا الشهر بالشهر الماضي.",
  "شنو المدفوعات اللي تحتاج مراجعة؟",
  "توقعلي التدفق النقدي للـ30 يوم الجاية.",
];
function AssistantBubble({ reply }) {
  const grounded = reply.kind === "answer" && reply.verified;
  return (
    <div className="max-w-full space-y-3">
      <div className="rounded-panel border border-line bg-surface p-4">
        <p className="whitespace-pre-wrap leading-8">{reply.answer_ar}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {grounded && (
            <Badge tone="pos">
              <BadgeCheck className="size-3.5" aria-hidden />
              أرقام مأخوذة من بياناتك ومتحقَّق منها
            </Badge>
          )}
          {reply.kind === "clarification" && <Badge tone="info">سؤال توضيحي</Badge>}
          {reply.degraded && (
            <Badge tone="warn">
              <AlertTriangle className="size-3.5" aria-hidden />
              وضع القواعد بسبب تعذّر الاتصال
            </Badge>
          )}
          {reply.kind === "fallback" && (
            <Badge tone="warn">
              <AlertTriangle className="size-3.5" aria-hidden />
              عرض مباشر من النظام
            </Badge>
          )}
        </div>
        {(reply.kind === "fallback" || reply.degraded) &&
          reply.warnings.map((w, i) => (
            <p key={i} className="mt-2 text-sm text-warn">
              {w}
            </p>
          ))}
      </div>
      {reply.evidence.map((ev, i) => (
        <EvidenceView key={i} ev={ev} />
      ))}
    </div>
  );
}
export function Assistant() {
  const status = useAsync(() => api.assistantStatus(), []);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  const nextId = useRef(1);
  const unavailable = status.data?.configured === false;
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);
  const send = async (q) => {
    const question = q.trim();
    if (!question || busy) return;
    const history = [];
    for (const m of msgs) {
      if (m.role === "user") history.push({ role: "user", content: m.text.slice(0, 2000) });
      else if (m.role === "assistant") history.push({ role: "assistant", content: m.reply.answer_ar.slice(0, 2000) });
    }
    const recentHistory = history.slice(-8);
    setMsgs((s) => [...s.filter((m) => m.role !== "error"), { id: nextId.current++, role: "user", text: question }]);
    setText("");
    setBusy(true);
    try {
      const reply = await api.chat(question, recentHistory);
      setMsgs((s) => [...s, { id: nextId.current++, role: "assistant", reply }]);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "unknown", "حدث خطأ غير متوقع");
      if (err.code === "ai_not_configured") status.reload();
      setMsgs((s) => [...s, { id: nextId.current++, role: "error", text: err.message, code: err.code, retryText: question }]);
    } finally {
      setBusy(false);
    }
  };
  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  };
  return (
    <div className="flex min-h-[calc(100vh-8.5rem)] flex-col gap-4">
      <PageHeader
        title="المساعد الذكي"
        subtitle="اسأل عن مبيعاتك وديونك بلهجتك. كل رقم في الجواب يأتي من بياناتك المسجلة، ويظهر تحته الدليل."
      />

      {unavailable && (
        <div role="alert" className="flex items-start gap-3 rounded-panel border border-[#efd8ab] bg-warn-bg px-4 py-3 text-warn">
          <AlertTriangle className="mt-1 size-5 shrink-0" aria-hidden />
          <div className="text-sm leading-7">
            <p className="font-bold">المساعد الذكي غير مفعّل</p>
            <p>{status.data?.message_ar}</p>
          </div>
        </div>
      )}
      {status.data?.provider === "rules" && (
        <div role="note" className="flex items-start gap-3 rounded-panel border border-[#c5d6f2] bg-info-bg px-4 py-3 text-info">
          <Info className="mt-1 size-5 shrink-0" aria-hidden />
          <div className="text-sm leading-7">
            <p className="font-bold">وضع القواعد (بدون ذكاء اصطناعي)</p>
            <p>{status.data.message_ar}</p>
          </div>
        </div>
      )}
      {status.error && !unavailable && (
        <p role="alert" className="text-sm text-neg">
          {status.error.message}
        </p>
      )}

      <div className="flex-1 space-y-5" aria-live="polite" aria-label="المحادثة">
        {msgs.length === 0 && (
          <div className="rounded-panel border border-dashed border-line-strong bg-surface px-5 py-8 text-center">
            <Sparkles className="mx-auto mb-2 size-6 text-info" aria-hidden />
            <p className="font-bold">جرّب أحد هذه الأسئلة</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted">
              يمكنك الكتابة بالعامية العراقية. إذا كان السؤال غير واضح (مثل الفترة الزمنية) سيسألك المساعد قبل أن يحسب.
            </p>
          </div>
        )}
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-start">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-panel bg-ink px-4 py-2.5 leading-7 text-white">{m.text}</p>
            </div>
          ) : m.role === "assistant" ? (
            <div key={m.id} className="flex justify-end">
              <div className="w-full max-w-3xl">
                <AssistantBubble reply={m.reply} />
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-end">
              <div role="alert" className="max-w-3xl rounded-panel border border-[#f2c5c3] bg-neg-bg px-4 py-3 text-neg">
                <p className="text-sm font-semibold">{m.text}</p>
                {m.code !== "ai_not_configured" && (
                  <Button className="mt-2 h-9" onClick={() => void send(m.retryText)} disabled={busy}>
                    إعادة المحاولة
                  </Button>
                )}
              </div>
            </div>
          ),
        )}
        {busy && (
          <div className="flex justify-end" role="status">
            <p className="flex items-center gap-2 rounded-panel border border-line bg-surface px-4 py-3 text-muted">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              جارٍ حساب الإجابة من بياناتك…
            </p>
          </div>
        )}
        <div ref={end} />
      </div>

      <div className="sticky bottom-0 -mx-4 space-y-2 border-t border-line bg-page/95 px-4 pb-3 pt-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex gap-2 overflow-x-auto pb-1" role="group" aria-label="أسئلة مقترحة">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              disabled={busy || unavailable}
              onClick={() => void send(q)}
              className="shrink-0 rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-sm font-medium hover:border-ink disabled:cursor-not-allowed disabled:text-faint disabled:hover:border-line-strong"
            >
              {q}
            </button>
          ))}
        </div>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send(text);
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            maxLength={1000}
            disabled={unavailable}
            aria-label="اكتب سؤالك"
            placeholder={unavailable ? "المساعد غير مفعّل" : "اكتب سؤالك هنا، مثلاً: شكد ربحت هذا الشهر؟"}
            className={cx(
              "max-h-40 min-h-11 w-full resize-none rounded-control border border-line-strong bg-surface px-3 py-2.5 placeholder:text-faint focus-visible:border-info disabled:bg-page",
            )}
          />
          <Button
            type="submit"
            variant="primary"
            className="h-11 shrink-0"
            disabled={!text.trim() || busy || unavailable}
            aria-label="إرسال"
          >
            <SendHorizonal className="size-4 rtl:-scale-x-100" aria-hidden />
            إرسال
          </Button>
        </form>
        <p className="text-xs text-muted">
          المساعد يقرأ بياناتك فقط ولا يستطيع تعديلها. الأرقام التقديرية (الربح، التوقعات) موسومة بكلمة «تقدير».
        </p>
      </div>
    </div>
  );
}
