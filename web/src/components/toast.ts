import { reactive } from "vue";

// Lightweight sonner-style notices: bottom-right, auto-dismiss, optional action.
export interface Toast {
  id: number;
  message: string;
  tone: "default" | "ok" | "fail";
  action?: { label: string; run: () => void };
}
export const toasts = reactive<Toast[]>([]);
let next = 1;
export function toast(message: string, options: Partial<Omit<Toast, "id" | "message">> = {}): void {
  const id = next++;
  toasts.push({ id, message, tone: options.tone || "default", action: options.action });
  setTimeout(() => dismiss(id), options.action ? 8000 : 4000);
}
export function dismiss(id: number): void {
  const index = toasts.findIndex((item) => item.id === id);
  if (index >= 0) toasts.splice(index, 1);
}
