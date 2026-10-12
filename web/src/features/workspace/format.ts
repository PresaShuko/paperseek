import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

/** Compact table dates: "今天 15:02" today, "10-07 21:14" this year, full date otherwise. */
export function useDates() {
  const { language } = useLocale();
  const u = useUi();
  const pad = (value: number) => String(value).padStart(2, "0");
  function short(value?: string | null): string {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const now = new Date();
    const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    if (date.toDateString() === now.toDateString()) return `${u("today")} ${time}`;
    if (date.getFullYear() === now.getFullYear()) return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`;
    return date.toLocaleDateString(language.value === "zh" ? "zh-CN" : "en");
  }
  function day(value?: string | null): string {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  function ago(value?: string | null): string {
    if (!value) return "";
    const minutes = Math.floor((Date.now() - Date.parse(value)) / 60000);
    if (Number.isNaN(minutes)) return "";
    if (minutes < 1) return u("agoNow");
    if (minutes < 60) return u("agoMin", { n: minutes });
    if (minutes < 1440) return u("agoHour", { n: Math.floor(minutes / 60) });
    return u("agoDay", { n: Math.floor(minutes / 1440) });
  }
  return { short, day, ago };
}
