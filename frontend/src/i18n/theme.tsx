import { useCallback, useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "localdub.theme";

function stored(): ThemePref {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* storage can be blocked */
  }
  return "system";
}

const systemDark = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;

/** Light / dark / follow Windows. Sets `data-theme` on <html>; the stylesheet does the rest. */
export function useTheme() {
  const [pref, setPrefState] = useState<ThemePref>(stored);
  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.theme = pref === "dark" || (pref === "system" && systemDark()) ? "dark" : "light";
    };
    apply();
    if (pref !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);
  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try {
      if (p === "system") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, p);
    } catch {
      /* ignore */
    }
  }, []);
  return { pref, setPref };
}
