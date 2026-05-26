import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface Toast {
  message: string;
  type: "success" | "error";
}

interface ToastContextValue {
  toast: Toast | null;
  showToast: (message: string, type: "success" | "error") => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

function ToastComponent({ toast }: { toast: Toast | null }) {
  if (!toast) return null;

  return createPortal(
    <div
      role="status"
      aria-live="polite"
      className={`fixed top-16 right-4 z-50 border px-4 py-2.5 font-courier text-xs tracking-wider uppercase backdrop-blur-sm ${
        toast.type === "success"
          ? "bg-success/15 text-success border-success/30"
          : "bg-destructive/15 text-destructive border-destructive/30"
      }`}
      style={{
        animation: "toast-in 200ms ease-out forwards",
      }}
    >
      {toast.message}
    </div>,
    document.body,
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);

  const showToast = useCallback(
    (message: string, type: "success" | "error") => {
      setToast({ message, type });
      setTimeout(() => setToast(null), 3000);
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ toast, showToast }}>
      {children}
      <ToastComponent toast={toast} />
    </ToastContext.Provider>
  );
}
