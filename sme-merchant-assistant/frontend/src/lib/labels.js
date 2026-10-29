export const TYPE_LABEL = {
  sale: "بيع",
  customer_payment: "تسديد زبون",
  expense: "مصروف",
  supplier_purchase: "شراء بضاعة",
  supplier_payment: "تسديد مورد",
};
export const METHOD_LABEL = { cash: "نقد", digital: "محفظة إلكترونية", bank: "بنك / بطاقة", credit: "آجل" };
export const STATUS_LABEL = { reconciled: "مطابقة", unreconciled: "غير مطابقة", excluded: "مستبعدة" };
export const FLAG_LABEL = {
  possible_duplicate: "احتمال تكرار",
  future_date: "تاريخ مستقبلي",
  amount_outlier: "مبلغ غير معتاد",
  customer_overpayment: "دفعة زائدة",
  unreconciled: "غير مطابقة",
};
export const SEVERITY_LABEL = { high: "عالية", medium: "متوسطة", low: "منخفضة" };
export const PERIOD_LABEL = {
  today: "اليوم",
  yesterday: "أمس",
  this_week: "هذا الأسبوع",
  last_week: "الأسبوع الماضي",
  this_month: "هذا الشهر",
  last_month: "الشهر الماضي",
  last_month_same_span: "الشهر الماضي (نفس المدة)",
  last_7_days: "آخر 7 أيام",
  last_30_days: "آخر 30 يوماً",
};
export const IMPORT_FIELD_LABEL = {
  date: "التاريخ",
  type: "النوع",
  amount: "المبلغ",
  description: "الوصف",
  reference: "المرجع",
  payment_method: "طريقة الدفع",
  customer: "الزبون",
  supplier: "المورد",
  category: "التصنيف",
  status: "الحالة",
  row: "الصف",
};
export const IMPORT_REQUIRED = ["date", "type", "amount", "description", "payment_method"];
export const IMPORT_FIELDS = [
  "date",
  "type",
  "amount",
  "description",
  "reference",
  "payment_method",
  "customer",
  "supplier",
  "category",
  "status",
];
/** Which party and payment methods each type allows (mirrors backend check_transaction_rules). */
export const TYPE_RULES = {
  sale: { customer: "optional", supplier: "none", credit: true },
  customer_payment: { customer: "required", supplier: "none", credit: false },
  expense: { customer: "none", supplier: "none", credit: false },
  supplier_purchase: { customer: "none", supplier: "optional", credit: true },
  supplier_payment: { customer: "none", supplier: "required", credit: false },
};
