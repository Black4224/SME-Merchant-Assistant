import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportWizard } from "../components/ImportWizard";
import { ToastProvider } from "../components/Toast";
import { SettingsProvider } from "../lib/settings";
import clean from "./fixtures/import_preview_clean.json";
import mapping from "./fixtures/import_preview_mapping.json";
import mixed from "./fixtures/import_preview_mixed.json";
import result from "./fixtures/import_result.json";
import { baseRoutes, fail, mockFetch } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const P = "/api/import/csv/preview",
  C = "/api/import/csv/confirm";
function setup(routes) {
  const api = mockFetch({ ...baseRoutes(), ...routes });
  const onDone = vi.fn(),
    onClose = vi.fn();
  render(
    <SettingsProvider>
      <ToastProvider>
        <ImportWizard open onClose={onClose} onDone={onDone} />
      </ToastProvider>
    </SettingsProvider>,
  );
  return { api, onDone, onClose };
}
const upload = async (name = "t.csv") => {
  const file = new File(["a,b\n1,2"], name, { type: "text/csv" });
  await userEvent.upload(await screen.findByLabelText("ملف CSV"), file);
  return file;
};
const confirmBtn = () => screen.getByRole("button", { name: /^استيراد \d+ معاملة$/ });
describe("CSV import wizard", () => {
  it("previews a file without importing anything, showing counts and what will be created", async () => {
    const { api } = setup({ [`POST ${P}`]: mixed });
    await upload();
    expect(await screen.findByText(/جديدة:/)).toHaveTextContent("جديدة: 2");
    expect(screen.getByText(/مكررة:/)).toHaveTextContent("مكررة: 1");
    expect(screen.getByText(/غير صالحة:/)).toHaveTextContent("غير صالحة: 1");
    expect(screen.getByText(/سيُنشأ زبائن جدد/).parentElement).toHaveTextContent("زبون جديد للاختبار"); // will_create
    expect(screen.getByText("مكررة، ستُتخطى")).toBeInTheDocument();
    expect(api.of("POST", C)).toHaveLength(0); // preview never commits
    expect(api.of("POST", P)[0].form.get("file")).toBeInstanceOf(File);
  });
  it("lists invalid rows with their line number, field and reason", async () => {
    setup({ [`POST ${P}`]: mixed });
    await upload();
    const bad = mixed.errors[0];
    const section = (await screen.findByText(/صفوف غير صالحة/)).closest("div");
    const reason = within(section).getByText(bad.errors[0].message);
    expect(reason.closest("li")).toHaveTextContent(`السطر ${bad.row_number}`);
  });
  it("blocks the import until the user explicitly chooses to skip invalid rows", async () => {
    const { api, onDone } = setup({ [`POST ${P}`]: mixed, [`POST ${C}`]: result });
    const file = await upload("mixed.csv");
    await screen.findByText(/جديدة:/);
    expect(confirmBtn()).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /تخطّي الصفوف غير الصالحة/ }));
    expect(confirmBtn()).toBeEnabled();
    await userEvent.click(confirmBtn());
    expect(await screen.findByText(/تم استيراد/)).toBeInTheDocument();
    const sent = api.of("POST", C)[0].form;
    expect(sent.get("skip_invalid")).toBe("true");
    expect(sent.get("expected_sha256")).toBe(mixed.file_sha256); // pins exactly the previewed file
    expect(sent.get("file").name).toBe(file.name);
    await userEvent.click(screen.getByRole("button", { name: "تم" }));
    expect(onDone).toHaveBeenCalledTimes(1); // parent refreshes its list
  });
  it("imports a clean file in one confirm", async () => {
    const { api } = setup({ [`POST ${P}`]: clean, [`POST ${C}`]: result });
    await upload();
    await screen.findByText(/جديدة:/);
    expect(confirmBtn()).toBeEnabled();
    await userEvent.click(confirmBtn());
    expect(await screen.findByText(/تم استيراد/)).toBeInTheDocument();
    expect(api.of("POST", C)[0].form.get("skip_invalid")).toBe("false");
  });
  it("asks you to map columns it doesn't recognise, then re-previews with your mapping", async () => {
    let step = 0;
    const { api } = setup({ [`POST ${P}`]: () => (step++ === 0 ? mapping : clean) });
    await upload();
    expect(await screen.findByText(/لم نتعرف على كل الأعمدة/)).toBeInTheDocument();
    const go = screen.getByRole("button", { name: "معاينة" });
    expect(go).toBeDisabled();
    const pick = async (label, column) => userEvent.selectOptions(screen.getByLabelText(new RegExp(`^${label}`)), column);
    await pick("التاريخ", "when");
    await pick("النوع", "kind");
    await pick("المبلغ", "iqd");
    await pick("الوصف", "memo");
    expect(go).toBeDisabled(); // still missing payment method
    await pick("طريقة الدفع", "how");
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(await screen.findByText(/جديدة:/)).toBeInTheDocument();
    expect(JSON.parse(api.of("POST", P)[1].form.get("mapping"))).toEqual({
      date: "when",
      type: "kind",
      amount: "iqd",
      description: "memo",
      payment_method: "how",
    });
  });
  it("refuses to map two fields to the same column", async () => {
    setup({ [`POST ${P}`]: mapping });
    await upload();
    await screen.findByText(/لم نتعرف على كل الأعمدة/);
    const pick = (label, col) => userEvent.selectOptions(screen.getByLabelText(new RegExp(`^${label}`)), col);
    await pick("التاريخ", "when");
    await pick("النوع", "when");
    await pick("المبلغ", "iqd");
    await pick("الوصف", "memo");
    await pick("طريقة الدفع", "how");
    expect(screen.getByRole("button", { name: "معاينة" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/أكثر من حقل/);
  });
  it("warns and disables import when the same file was imported before", async () => {
    setup({ [`POST ${P}`]: { ...clean, already_imported: true, counts: { total: 1, valid: 0, duplicate: 1, invalid: 0 } } });
    await upload();
    expect(await screen.findByText(/تم استيراد هذا الملف سابقاً/)).toBeInTheDocument();
    expect(confirmBtn()).toBeDisabled();
  });
  it("disables import when nothing new would be added", async () => {
    setup({ [`POST ${P}`]: { ...clean, counts: { total: 1, valid: 0, duplicate: 1, invalid: 0 }, rows: [] } });
    await upload();
    await screen.findByText(/جديدة:/);
    expect(confirmBtn()).toBeDisabled();
  });
  it("shows the server's reason when the file can't be read, and lets you pick another", async () => {
    setup({ [`POST ${P}`]: fail(422, "bad_csv", "السطر 2 يحتوي على 4 أعمدة بينما العنوان فيه 2.") });
    await upload();
    expect(await screen.findByText(/السطر 2 يحتوي على 4 أعمدة/)).toBeInTheDocument();
    expect(screen.getByText(/اسحب ملف CSV هنا/)).toBeInTheDocument();
  });
  it("surfaces a rejected confirm (e.g. file changed or already imported) without losing the preview", async () => {
    setup({ [`POST ${P}`]: clean, [`POST ${C}`]: fail(409, "file_already_imported", "هذا الملف نفسه تم استيراده مسبقاً") });
    await upload();
    await screen.findByText(/جديدة:/);
    await userEvent.click(confirmBtn());
    expect(await screen.findByText("هذا الملف نفسه تم استيراده مسبقاً")).toBeInTheDocument();
    expect(screen.getByText(/جديدة:/)).toBeInTheDocument();
  });
  it("closes without refreshing when nothing was imported", async () => {
    const { onDone, onClose } = setup({});
    const closers = screen.getAllByRole("button", { name: "إغلاق" }); // header X and footer button
    expect(closers).toHaveLength(2);
    await userEvent.click(closers[1]);
    expect(onClose).toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });
});
