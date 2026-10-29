import { api } from "../api/endpoints";
import { useAsync } from "./useAsync";
/** Customers, suppliers and categories for form dropdowns. */
export function useLookups() {
  const customers = useAsync(() => api.customers({ page_size: 200 }), []);
  const suppliers = useAsync(() => api.suppliers(), []);
  const categories = useAsync(() => api.categories(), []);
  return {
    customers: customers.data?.items.map((c) => ({ id: c.customer_id, name: c.name })) ?? [],
    suppliers: suppliers.data?.items.map((s) => ({ id: s.supplier_id, name: s.name })) ?? [],
    categories: categories.data?.items ?? [],
    reload: () => {
      customers.reload();
      suppliers.reload();
    },
  };
}
