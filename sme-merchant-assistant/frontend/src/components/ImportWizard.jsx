import { CheckCircle2, FileUp, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { IMPORT_FIELDS, IMPORT_FIELD_LABEL, IMPORT_REQUIRED, TYPE_LABEL } from "../lib/labels";
import { fmtDateShort } from "../lib/format";
import { Money } from "./Money";
import { Modal } from "./Modal";
import { Badge, Button, ErrorBanner, Spinner, cx, inputCls } from "./ui";
const TEMPLATE =
  "date,type,amount,description,reference,payment_method,customer,supplier,category,status\n2026-10-01,sale,150000,بيع نقدي,INV-1,cash,,,مبيعات,\n2026-10-02,sale,250000,بيع آجل,INV-2,credit,أحمد علي,,مبيعات,\n";
export function ImportWizard({ open, onClose, onDone }) {
  const [step, setStep] = useState("choose");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [draft, setDraft] = useState({});
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const input = useRef(null);
  const reset = () => {
    setStep("choose");
    setFile(null);
    setPreview(null);
    setMapping(null);
    setDraft({});
    setSkipInvalid(false);
    setError(null);
    setResult(null);
  };
  const close = () => {
    if (step === "done") onDone();
    reset();
    onClose();
  };
  const run = async (f, m) => {
    setBusy(true);
    setError(null);
    try {
      const p = await api.previewImport(f, m);
      setPreview(p);
      if (p.needs_mapping) {
        setDraft({ ...p.suggested_mapping, ...(m ?? {}) });
        setStep("mapping");
      } else setStep("preview");
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "حدث خطأ غير متوقع"));
      setStep("choose");
    } finally {
      setBusy(false);
    }
  };
  const pick = (f) => {
    if (f) {
      setFile(f);
      setMapping(null);
      void run(f, null);
    }
  };
  const draftOk =
    IMPORT_REQUIRED.every((k) => draft[k]) &&
    new Set(Object.values(draft).filter(Boolean)).size === Object.values(draft).filter(Boolean).length;
  const confirm = async () => {
    if (!file || !preview) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.confirmImport(file, { mapping, skipInvalid, sha256: preview.file_sha256 }));
      setStep("done");
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "حدث خطأ غير متوقع"));
    } finally {
      setBusy(false);
    }
  };
  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob(["\ufeff" + TEMPLATE], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "قالب_المعاملات.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  const c = preview?.counts;
  const blocked = !preview || preview.already_imported || !c || c.valid === 0 || (c.invalid > 0 && !skipInvalid);
  return (
    <Modal
      open={open}
      title="استيراد معاملات من ملف CSV"
      onClose={close}
      size="xl"
      footer={
        step === "preview" && preview ? (
          <>
            <Button onClick={reset} disabled={busy}>
              اختيار ملف آخر
            </Button>
            {mapping && (
              <Button onClick={() => setStep("mapping")} disabled={busy}>
                تغيير ربط الأعمدة
              </Button>
            )}
            <Button variant="primary" onClick={confirm} loading={busy} disabled={blocked}>
              استيراد <span className="num">{c?.valid ?? 0}</span> معاملة
            </Button>
          </>
        ) : step === "mapping" ? (
          <>
            <Button onClick={reset}>اختيار ملف آخر</Button>
            <Button
              variant="primary"
              disabled={!draftOk}
              loading={busy}
              onClick={() => {
                setMapping(draft);
                void run(file, draft);
              }}
            >
              معاينة
            </Button>
          </>
        ) : step === "done" ? (
          <Button variant="primary" onClick={close}>
            تم
          </Button>
        ) : (
          <Button onClick={close}>إغلاق</Button>
        )
      }
    >
      <div className="space-y-4">
        {error && <ErrorBanner error={error} />}

        {step === "choose" && (
          <>
            <div
              role="button"
              tabIndex={0}
              aria-label="اختيار ملف CSV"
              onClick={() => input.current?.click()}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                pick(e.dataTransfer.files?.[0]);
              }}
              className="flex cursor-pointer flex-col items-center gap-2 rounded-panel border-2 border-dashed border-line-strong px-6 py-12 text-center hover:border-ink"
            >
              <FileUp className="size-8 text-info" aria-hidden />
              <p className="font-bold">اسحب ملف CSV هنا أو اضغط للاختيار</p>
              <p className="text-sm text-muted">سنفحص الملف أولاً ولن يُحفظ شيء قبل أن تؤكد.</p>
              <input
                ref={input}
                type="file"
                accept=".csv,.txt,text/csv"
                className="sr-only"
                aria-label="ملف CSV"
                onChange={(e) => {
                  pick(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </div>
            {busy && <Spinner label="جارٍ فحص الملف…" />}
            <ul className="list-disc space-y-1 ps-5 text-sm text-muted">
              <li>
                الأعمدة المطلوبة: التاريخ، النوع، المبلغ، الوصف، طريقة الدفع. أسماء الأعمدة العربية والإنجليزية مدعومة، وإن لم نتعرف عليها
                ستربطها بنفسك.
              </li>
              <li>التاريخ بصيغة 2026-10-15 أو 15/10/2026 (اليوم أولاً). المبلغ بالدينار بدون كسور.</li>
              <li>الصفوف الموجودة مسبقاً تُتخطى تلقائياً، واستيراد الملف نفسه مرتين غير ممكن.</li>
            </ul>
            <Button variant="ghost" onClick={downloadTemplate}>
              تحميل قالب جاهز
            </Button>
          </>
        )}

        {step === "mapping" && preview && (
          <>
            <p className="text-sm text-muted">
              لم نتعرف على كل الأعمدة في <b>{preview.filename}</b>. اربط كل حقل بالعمود المناسب من ملفك. الحقول المميزة بـ * مطلوبة.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {IMPORT_FIELDS.map((fld) => (
                <label key={fld} className="block">
                  <span className="mb-1 block text-sm font-semibold">
                    {IMPORT_FIELD_LABEL[fld]}
                    {IMPORT_REQUIRED.includes(fld) && <span className="text-neg"> *</span>}
                  </span>
                  <select
                    className={inputCls()}
                    value={draft[fld] ?? ""}
                    onChange={(e) =>
                      setDraft((d) => {
                        const n = { ...d };
                        if (e.target.value) n[fld] = e.target.value;
                        else delete n[fld];
                        return n;
                      })
                    }
                  >
                    <option value="">— غير مربوط —</option>
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            {!draftOk && (
              <p role="alert" className="text-sm text-warn">
                اربط كل الحقول المطلوبة، ولا تربط عموداً واحداً بأكثر من حقل.
              </p>
            )}
          </>
        )}

        {step === "preview" && preview && c && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="pos">
                جديدة: <span className="num">{c.valid}</span>
              </Badge>
              <Badge tone="neutral">
                مكررة: <span className="num">{c.duplicate}</span>
              </Badge>
              <Badge tone={c.invalid ? "neg" : "neutral"}>
                غير صالحة: <span className="num">{c.invalid}</span>
              </Badge>
              <span className="text-sm text-muted">
                من أصل <span className="num">{c.total}</span> صف في {preview.filename}
              </span>
            </div>
            {preview.already_imported && (
              <p
                role="alert"
                className="flex items-center gap-2 rounded-control border border-[#f2c5c3] bg-neg-bg px-3 py-2 text-sm font-medium text-neg"
              >
                <TriangleAlert className="size-4" aria-hidden />
                تم استيراد هذا الملف سابقاً ولا يمكن استيراده مرة ثانية.
              </p>
            )}
            {["customers", "suppliers", "categories"].map(
              (k) =>
                preview.will_create[k].length > 0 && (
                  <p key={k} className="text-sm text-muted">
                    <b className="text-ink">سيُنشأ {{ customers: "زبائن", suppliers: "موردون", categories: "تصنيفات" }[k]} جدد: </b>
                    {preview.will_create[k].join("، ")}
                  </p>
                ),
            )}

            {c.invalid > 0 && (
              <div className="rounded-panel border border-[#f2c5c3]">
                <h3 className="border-b border-[#f2c5c3] bg-neg-bg px-3 py-2 text-sm font-bold text-neg">
                  صفوف غير صالحة (<span className="num">{c.invalid}</span>)
                </h3>
                <ul className="max-h-56 divide-y divide-line overflow-y-auto text-sm">
                  {preview.errors.map((r) => (
                    <li key={r.row_number} className="px-3 py-2">
                      <b>
                        السطر <span className="num">{r.row_number}</span>:
                      </b>{" "}
                      {r.errors.map((e, i) => (
                        <span key={i} className="me-2">
                          {IMPORT_FIELD_LABEL[e.field] ?? e.field}: <span className="text-neg">{e.message}</span>
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
                {preview.errors_truncated && <p className="px-3 py-2 text-xs text-muted">عُرضت أول 500 مشكلة فقط.</p>}
                <label className="flex items-center gap-2 border-t border-line px-3 py-2.5 text-sm font-semibold">
                  <input type="checkbox" className="size-4" checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} />
                  تخطّي الصفوف غير الصالحة واستيراد الباقي
                </label>
              </div>
            )}

            <div className="overflow-x-auto rounded-panel border border-line">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr>
                    {["السطر", "الحالة", "التاريخ", "النوع", "الوصف", "الطرف", "المبلغ"].map((h) => (
                      <th key={h} className="border-b border-line bg-page px-3 py-2 text-start text-xs font-semibold text-muted">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows
                    .filter((r) => r.status !== "invalid")
                    .map((r) => (
                      <tr key={r.row_number} className={cx(r.status === "duplicate" && "text-faint")}>
                        <td className="border-b border-line px-3 py-2">
                          <span className="num">{r.row_number}</span>
                        </td>
                        <td className="border-b border-line px-3 py-2">
                          {r.status === "valid" ? <Badge tone="pos">جديدة</Badge> : <Badge>مكررة، ستُتخطى</Badge>}
                        </td>
                        <td className="border-b border-line px-3 py-2">{fmtDateShort(String(r.data.date))}</td>
                        <td className="border-b border-line px-3 py-2">{TYPE_LABEL[r.data.type]}</td>
                        <td className="border-b border-line px-3 py-2">
                          {String(r.data.description)}
                          {r.warnings
                            .filter((w) => !w.includes("موجودة مسبقاً"))
                            .map((w, i) => (
                              <span key={i} className="block text-xs text-warn">
                                {w}
                              </span>
                            ))}
                        </td>
                        <td className="border-b border-line px-3 py-2">{String(r.data.customer ?? r.data.supplier ?? "—")}</td>
                        <td className="border-b border-line px-3 py-2">
                          <Money value={Number(r.data.amount_iqd)} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {preview.rows.length < c.total && (
              <p className="text-xs text-muted">
                المعاينة تعرض أول <span className="num">{preview.rows.length}</span> صف؛ سيُستورد الملف كاملاً.
              </p>
            )}
          </>
        )}

        {step === "done" && result && (
          <div className="space-y-3 py-4 text-center">
            <CheckCircle2 className="mx-auto size-10 text-pos" aria-hidden />
            <p className="text-lg font-bold">
              تم استيراد <span className="num">{result.imported}</span> معاملة
            </p>
            <p className="text-sm text-muted">
              تخطّينا <span className="num">{result.skipped_duplicates}</span> مكررة و<span className="num">{result.skipped_invalid}</span>{" "}
              غير صالحة.
              {result.created.customers.length > 0 && <> أُنشئ زبائن: {result.created.customers.join("، ")}.</>}
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}
