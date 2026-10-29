import { createContext, useContext } from "react";
import { api } from "../api/endpoints";
import { useAsync } from "./useAsync";
const SettingsCtx = createContext({ settings: null, error: null, reload: () => {}, currency: "د.ع" });
export const useSettings = () => useContext(SettingsCtx);
export function SettingsProvider({ children }) {
  const { data, error, reload } = useAsync(() => api.settings(), []);
  return (
    <SettingsCtx.Provider value={{ settings: data, error, reload, currency: data?.currency_display ?? "د.ع" }}>
      {children}
    </SettingsCtx.Provider>
  );
}
