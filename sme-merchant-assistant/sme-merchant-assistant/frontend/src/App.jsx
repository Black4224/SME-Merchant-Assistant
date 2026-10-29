import { Suspense, lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { Spinner } from "./components/ui";
import { SettingsProvider } from "./lib/settings";
const page = (loader, name) => lazy(() => loader().then((m) => ({ default: m[name] })));
const Dashboard = page(() => import("./pages/Dashboard"), "Dashboard");
const Assistant = page(() => import("./pages/Assistant"), "Assistant");
const Transactions = page(() => import("./pages/Transactions"), "Transactions");
const Customers = page(() => import("./pages/Customers"), "Customers");
const CustomerDetail = page(() => import("./pages/CustomerDetail"), "CustomerDetail");
const Reports = page(() => import("./pages/Reports"), "Reports");
const SettingsPage = page(() => import("./pages/SettingsPage"), "SettingsPage");
export function AppRoutes() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/customers/:id" element={<CustomerDetail />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<p className="py-20 text-center text-muted">الصفحة غير موجودة.</p>} />
      </Routes>
    </Suspense>
  );
}
export default function App() {
  return (
    <BrowserRouter>
      <SettingsProvider>
        <ToastProvider>
          <Layout>
            <AppRoutes />
          </Layout>
        </ToastProvider>
      </SettingsProvider>
    </BrowserRouter>
  );
}
