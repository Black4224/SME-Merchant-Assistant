import { CheckCircle2, FlaskConical, ServerCrash } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { PageHeader } from "../components/Layout";
import { ConfirmDialog } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, ErrorBanner, Field, Spinner, inputCls } from "../components/ui";
import { fmtDate } from "../lib/format";
import { useSettings } from "../lib/settings";
import { useAsync } from "../lib/useAsync";
function SettingsBody({ settings, reload }) {
  const health = useAsync(() => api.health(), []);
  const toast = useToast();
  const [name, setName] = useState(settings.business_name);
  const [days, setDays] = useState(String(settings.credit_terms_days));
  const [currency, setCurrency] = useState(settings.currency_display);
  const [fieldErr, setFieldErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [resetting, setResetting] = useState(false);
  const dayNum = Number(days);
  const daysOk = Number.isInteger(dayNum) && dayNum >= 1 && dayNum <= 365;
  const dirty = name.trim() !== settings.business_name || dayNum !== settings.credit_terms_days || currency !== settings.currency_display;
  const save = async () => {
    if (!name.trim()) {
      setFieldErr("اسم النشاط مطلوب");
      return;
    }
    if (!daysOk) {
      setFieldErr("مدة الائتمان يجب أن تكون عدداً صحيحاً بين 1 و365");
      return;
    }
    setFieldErr("");
    setSaving(true);
    try {
      await api.updateSettings({ business_name: name.trim(), credit_terms_days: dayNum, currency_display: currency });
      toast("تم حفظ الإعدادات");
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "تعذّر الحفظ", "err");
    } finally {
      setSaving(false);
    }
  };
  const reset = async () => {
    setResetting(true);
    try {
      const r = await api.resetDemo();
      toast(`أُعيد تحميل البيانات التجريبية (${r.transactions_loaded} معاملة)`);
      setResetOpen(false);
      setTyped("");
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "تعذّرت إعادة التحميل", "err");
    } finally {
      setResetting(false);
    }
  };
  return (
    <>
      <PageHeader title="الإعدادات" />
      {settings.is_demo_data && (
        <div role="note" className="flex items-start gap-3 rounded-panel border border-[#efd8ab] bg-warn-bg px-4 py-3 text-warn">
          <FlaskConical className="mt-1 size-5 shrink-0" aria-hidden />
          <div>
            <p className="font-bold">التطبيق يعمل حالياً ببيانات تجريبية اصطناعية</p>
            <p className="text-sm leading-7">
              {settings.demo_notice_ar} كل الأسماء والمبالغ مُختلقة. تاريخ «اليوم» في هذه البيانات مثبّت على{" "}
              {fmtDate(settings.reference_date)} ليبقى العرض قابلاً للتكرار.
            </p>
          </div>
        </div>
      )}

      <Card title="النشاط التجاري">
        <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <Field label="اسم النشاط" className="sm:col-span-2">
            <input className={inputCls()} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="مدة الائتمان (أيام)" hint="الفاتورة الآجلة غير المسددة بعد هذه المدة تُعدّ متأخرة">
            <input
              inputMode="numeric"
              className={inputCls(!daysOk) + " num text-start"}
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
          </Field>
          <Field label="عرض العملة" hint="يغيّر الرمز المعروض في الواجهة فقط">
            <select className={inputCls()} value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="د.ع">د.ع (دينار عراقي)</option>
              <option value="IQD">IQD</option>
            </select>
          </Field>
        </div>
        {fieldErr && (
          <p role="alert" className="mt-3 text-sm text-neg">
            {fieldErr}
          </p>
        )}
        <Button variant="primary" className="mt-4" onClick={save} loading={saving} disabled={!dirty}>
          حفظ الإعدادات
        </Button>
      </Card>

      <Card title="المساعد الذكي">
        <div className="flex flex-wrap items-center gap-3">
          {settings.ai.provider === "rules" ? (
            <Badge tone="info">وضع القواعد (بدون ذكاء اصطناعي)</Badge>
          ) : settings.ai.configured ? (
            <Badge tone="pos">
              <CheckCircle2 className="size-3.5" aria-hidden />
              مفعّل
            </Badge>
          ) : (
            <Badge tone="warn">غير مفعّل</Badge>
          )}
          <span className="text-sm text-muted">
            المزوّد: <span className="num">{settings.ai.provider}</span>
          </span>
        </div>
        {settings.ai.provider === "rules" && <p className="mt-3 text-sm leading-7 text-muted">{settings.ai.message_ar}</p>}
        {!settings.ai.configured && (
          <div className="mt-3 space-y-1 text-sm leading-7 text-muted">
            <p>{settings.ai.message_ar}</p>
            <p>
              لتفعيله: أضف <code className="num rounded bg-page px-1.5">GROQ_API_KEY</code> و
              <code className="num rounded bg-page px-1.5">GROQ_MODEL</code> في ملف <code className="num rounded bg-page px-1.5">.env</code>{" "}
              ثم أعد تشغيل الخادم.
            </p>
          </div>
        )}
      </Card>

      <Card title="إدارة البيانات">
        <dl className="grid max-w-2xl gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted">عدد المعاملات</dt>
            <dd className="text-lg font-bold num">{settings.transactions_count}</dd>
          </div>
          <div>
            <dt className="text-muted">نوع البيانات</dt>
            <dd>{settings.is_demo_data ? <Badge tone="warn">تجريبية</Badge> : <Badge tone="info">بياناتك</Badge>}</dd>
          </div>
        </dl>
        <p className="mt-3 max-w-2xl text-sm leading-7 text-muted">
          للاستيراد استخدم زر «استيراد CSV» في صفحة المعاملات. إعادة تحميل البيانات التجريبية تحذف كل المعاملات والزبائن الحاليين وتستبدلها
          بالبيانات التجريبية.
        </p>
        <Button variant="danger" className="mt-4" onClick={() => setResetOpen(true)}>
          إعادة تحميل البيانات التجريبية
        </Button>
      </Card>

      <Card title="حالة الخادم">
        {health.error ? (
          <p className="flex items-center gap-2 text-neg">
            <ServerCrash className="size-4" aria-hidden />
            {health.error.message}
          </p>
        ) : health.data ? (
          <p className="flex items-center gap-2 text-pos">
            <CheckCircle2 className="size-4" aria-hidden />
            الخادم يعمل وقاعدة البيانات متصلة
          </p>
        ) : (
          <Spinner label="جارٍ الفحص…" />
        )}
      </Card>

      <ConfirmDialog
        open={resetOpen}
        title="إعادة تحميل البيانات التجريبية"
        danger
        confirmLabel="حذف كل شيء وإعادة التحميل"
        loading={resetting}
        confirmDisabled={typed !== "RESET"}
        onClose={() => {
          setResetOpen(false);
          setTyped("");
        }}
        onConfirm={() => void reset()}
      >
        <p className="font-semibold text-neg">سيتم حذف كل البيانات الحالية نهائياً، بما فيها أي معاملات أدخلتها أو استوردتها.</p>
        <Field label="للتأكيد اكتب RESET">
          <input className={inputCls() + " num text-start"} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </Field>
        {typed !== "RESET" && typed.length > 0 && <p className="text-xs text-muted">اكتب الكلمة بالأحرف الكبيرة تماماً.</p>}
      </ConfirmDialog>
    </>
  );
}

export function SettingsPage() {
  const { settings, error, reload } = useSettings();
  if (error && !settings) return <ErrorBanner error={error} onRetry={reload} />;
  if (!settings) return <Spinner />;
  // Remount the form whenever the saved values change (after saving or after a demo reset).
  const key = `${settings.business_name}|${settings.credit_terms_days}|${settings.currency_display}|${settings.transactions_count}`;
  return <SettingsBody key={key} settings={settings} reload={reload} />;
}
