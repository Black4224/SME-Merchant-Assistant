import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import clarification from "./fixtures/assistant_clarification.json";
import cashflow from "./fixtures/assistant_cashflow.json";
import compare from "./fixtures/assistant_compare.json";
import debts from "./fixtures/assistant_debts.json";
import fallback from "./fixtures/assistant_fallback.json";
import { baseRoutes, fail, mockFetch, renderAt } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const ok = { configured: true, provider: "groq", message_ar: null };
const routes = (chat) => ({ ...baseRoutes(), "GET /api/assistant/status": ok, "POST /api/assistant/chat": chat });
const chip = (name) => screen.findByRole("button", { name });
describe("Assistant", () => {
  it("answers an example question and shows verifiable evidence under the answer", async () => {
    const api = mockFetch(routes(debts));
    renderAt("/assistant");
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    expect(await screen.findByText(debts.answer_ar)).toBeInTheDocument();
    expect(api.of("POST", "/api/assistant/chat")[0].body).toEqual({ message: "منو بعده ما دايفعلي؟", history: [] });
    expect(screen.getByText("أرقام مأخوذة من بياناتك ومتحقَّق منها")).toBeInTheDocument();
    const ev = screen.getByRole("article", { name: /الدليل: ديون الزبائن/ });
    expect(within(ev).getByText("إجمالي الديون")).toBeInTheDocument();
    expect(within(ev).getAllByText("8,470,750").length).toBeGreaterThan(0);
    expect(within(ev).getByText(/أساس الحساب/)).toBeInTheDocument();
    expect(within(ev).getByText(/المعاملات الداعمة/)).toBeInTheDocument();
    const names = debts.evidence[0].table.rows.map((r) => r.customer);
    for (const n of names) expect(within(ev).getAllByText(n).length).toBeGreaterThan(0); // every supporting customer is visible
  });
  it("sends earlier turns as history on the next question", async () => {
    const api = mockFetch(routes(debts));
    renderAt("/assistant");
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    await screen.findByText(debts.answer_ar);
    await userEvent.type(screen.getByRole("textbox", { name: "اكتب سؤالك" }), "وشكد المتأخر؟{Enter}");
    await waitFor(() => expect(api.of("POST", "/api/assistant/chat")).toHaveLength(2));
    expect(api.of("POST", "/api/assistant/chat")[1].body.history).toEqual([
      { role: "user", content: "منو بعده ما دايفعلي؟" },
      { role: "assistant", content: debts.answer_ar },
    ]);
  });
  it("shows both periods for a comparison and flags the estimate", async () => {
    mockFetch(routes(compare));
    renderAt("/assistant");
    await userEvent.click(await chip("قارنلي مبيعات هذا الشهر بالشهر الماضي."));
    const ev = await screen.findByRole("article", { name: /مقارنة فترتين/ });
    expect(within(ev).getByText(/مقارنة مع/)).toBeInTheDocument();
    expect(within(ev).getAllByText("تقدير").length).toBeGreaterThan(0);
    expect(within(ev).getByText("نسبة التغير في المبيعات")).toBeInTheDocument();
  });
  it("marks projections as estimates and explains there are no single supporting transactions", async () => {
    mockFetch(routes(cashflow));
    renderAt("/assistant");
    await userEvent.click(await chip("توقعلي التدفق النقدي للـ30 يوم الجاية."));
    const ev = await screen.findByRole("article", { name: /توقع التدفق النقدي/ });
    expect(within(ev).getAllByText("تقدير").length).toBeGreaterThan(0);
    expect(within(ev).getByText(/لا توجد معاملات مفردة تثبته/)).toBeInTheDocument();
    expect(within(ev).getByText(/ليس ضماناً|وليس ضماناً/)).toBeInTheDocument();
  });
  it("renders a clarification question differently from an answer", async () => {
    mockFetch(routes(clarification));
    renderAt("/assistant");
    await userEvent.click(await chip("شكد مبيعاتي اليوم؟"));
    expect(await screen.findByText(clarification.answer_ar)).toBeInTheDocument();
    expect(screen.getByText("سؤال توضيحي")).toBeInTheDocument();
    expect(screen.queryByText(/أرقام مأخوذة من بياناتك/)).not.toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
  it("when the model's wording was rejected, shows the system's figures and says so", async () => {
    mockFetch(routes(fallback));
    renderAt("/assistant");
    await userEvent.click(await chip("شكد مبيعاتي اليوم؟"));
    expect(await screen.findByText("عرض مباشر من النظام")).toBeInTheDocument();
    expect(screen.getByText(fallback.warnings[0])).toBeInTheDocument();
    expect(screen.queryByText(/25,000,000/)).not.toBeInTheDocument(); // the hallucinated figure is never shown
    expect(screen.queryByText(/أرقام مأخوذة من بياناتك/)).not.toBeInTheDocument();
    expect(screen.getByRole("article")).toBeInTheDocument();
  });
  it("is disabled with a clear explanation when no API key is configured", async () => {
    const api = mockFetch({
      ...routes(debts),
      "GET /api/assistant/status": { configured: false, provider: "groq", message_ar: "مفتاح الذكاء الاصطناعي غير مضبوط." },
    });
    renderAt("/assistant");
    expect(await screen.findByText("المساعد الذكي غير مفعّل")).toBeInTheDocument();
    expect(screen.getByText(/مفتاح الذكاء الاصطناعي غير مضبوط/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "اكتب سؤالك" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "شكد مبيعاتي اليوم؟" })).toBeDisabled();
    expect(api.of("POST", "/api/assistant/chat")).toHaveLength(0);
  });
  it("in offline rules mode it says plainly that this is not an AI model, and stays usable", async () => {
    const note = "وضع القواعد (بدون ذكاء اصطناعي): يفهم أسئلة محددة بصيغ شائعة فقط.";
    const api = mockFetch({ ...routes(debts), "GET /api/assistant/status": { configured: true, provider: "rules", message_ar: note } });
    renderAt("/assistant");
    const banner = await screen.findByRole("note");
    expect(banner).toHaveTextContent("وضع القواعد (بدون ذكاء اصطناعي)");
    expect(banner).toHaveTextContent("يفهم أسئلة محددة");
    expect(screen.queryByText("المساعد الذكي غير مفعّل")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "اكتب سؤالك" })).toBeEnabled();
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    expect(await screen.findByText(debts.answer_ar)).toBeInTheDocument();
    expect(api.of("POST", "/api/assistant/chat")).toHaveLength(1);
  });

  it("a real AI provider shows no rules-mode notice", async () => {
    mockFetch(routes(debts));
    renderAt("/assistant");
    await chip("منو بعده ما دايفعلي؟");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("labels an answer that was produced by the offline rules mode after the AI provider failed", async () => {
    const note = "تعذّر الاتصال بمزوّد الذكاء الاصطناعي مؤقتاً، لذلك أُجيب بوضع القواعد (بدون ذكاء اصطناعي).";
    mockFetch(routes({ ...debts, degraded: true, warnings: [note] }));
    renderAt("/assistant");
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    expect(await screen.findByText(debts.answer_ar)).toBeInTheDocument();
    expect(screen.getByText("وضع القواعد بسبب تعذّر الاتصال")).toBeInTheDocument();
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /ديون الزبائن/ })).toBeInTheDocument(); // evidence is still shown
  });

  it("an ordinary answer carries no degraded label", async () => {
    mockFetch(routes(debts));
    renderAt("/assistant");
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    await screen.findByText(debts.answer_ar);
    expect(screen.queryByText("وضع القواعد بسبب تعذّر الاتصال")).not.toBeInTheDocument();
  });

  it("shows a provider failure inline with a retry that re-sends the same question", async () => {
    let attempts = 0;
    const api = mockFetch(
      routes(() => (++attempts === 1 ? fail(502, "ai_rate_limit", "تم تجاوز حد الطلبات لدى مزوّد الذكاء الاصطناعي.") : debts)),
    );
    renderAt("/assistant");
    await userEvent.click(await chip("منو بعده ما دايفعلي؟"));
    expect(await screen.findByText(/تم تجاوز حد الطلبات/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "إعادة المحاولة" }));
    expect(await screen.findByText(debts.answer_ar)).toBeInTheDocument();
    expect(api.of("POST", "/api/assistant/chat").map((c) => c.body.message)).toEqual(["منو بعده ما دايفعلي؟", "منو بعده ما دايفعلي؟"]);
    expect(screen.queryByText(/تم تجاوز حد الطلبات/)).not.toBeInTheDocument();
  });
  it("a 503 from the server (key removed meanwhile) shows the reason and offers no pointless retry", async () => {
    mockFetch(routes(fail(503, "ai_not_configured", "المساعد الذكي غير مفعّل لأن مفتاح الذكاء الاصطناعي غير مضبوط.")));
    renderAt("/assistant");
    await userEvent.click(await chip("شكد مبيعاتي اليوم؟"));
    expect(await screen.findAllByText(/المساعد الذكي غير مفعّل/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "إعادة المحاولة" })).not.toBeInTheDocument();
  });
  it("shows a loading state while waiting and blocks double sending", async () => {
    let release;
    const api = mockFetch(
      routes(
        () =>
          new Promise((r) => {
            release = r;
          }),
      ),
    );
    renderAt("/assistant");
    await userEvent.click(await chip("شكد مبيعاتي اليوم؟"));
    expect(await screen.findByText(/جارٍ حساب الإجابة/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "منو بعده ما دايفعلي؟" })).toBeDisabled();
    release(clarification);
    await screen.findByText(clarification.answer_ar);
    expect(api.of("POST", "/api/assistant/chat")).toHaveLength(1);
  });
  it("Enter sends, Shift+Enter adds a line, and blank input cannot be sent", async () => {
    const api = mockFetch(routes(clarification));
    renderAt("/assistant");
    const box = await screen.findByRole("textbox", { name: "اكتب سؤالك" });
    expect(screen.getByRole("button", { name: "إرسال" })).toBeDisabled();
    await userEvent.type(box, "   ");
    expect(screen.getByRole("button", { name: "إرسال" })).toBeDisabled();
    await userEvent.clear(box);
    await userEvent.type(box, "سطر أول{Shift>}{Enter}{/Shift}سطر ثان");
    expect(api.of("POST", "/api/assistant/chat")).toHaveLength(0);
    expect(box.value).toBe("سطر أول\nسطر ثان");
    await userEvent.type(box, "{Enter}");
    await waitFor(() => expect(api.of("POST", "/api/assistant/chat")).toHaveLength(1));
    expect(api.of("POST", "/api/assistant/chat")[0].body.message).toBe("سطر أول\nسطر ثان");
  });
});
