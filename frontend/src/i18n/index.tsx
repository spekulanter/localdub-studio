import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setApiLang } from "../api";
import { sk } from "./sk";

export type Lang = "en" | "sk";
export const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "sk", label: "Slovenčina" },
];

type Vars = Record<string, string | number>;
const dictionaries: Record<Lang, Record<string, string>> = { en: {}, sk };
const STORAGE_KEY = "localdub.lang";

/** English text in, text in the chosen language out. Unknown strings stay English. `{name}` is replaced. */
export function translate(lang: Lang, text: string, vars?: Vars): string {
  const out = dictionaries[lang][text] ?? text;
  return vars ? out.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? `{${k}}`)) : out;
}

function initialLang(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "sk") return saved;
  } catch {
    /* storage can be blocked */
  }
  return typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("sk") ? "sk" : "en";
}

interface Value {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (text: string, vars?: Vars) => string;
}

const I18nContext = createContext<Value>({ lang: "en", setLang: () => undefined, t: (s, v) => translate("en", s, v) });

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initial ?? initialLang);
  setApiLang(lang);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);
  const value = useMemo<Value>(() => ({ lang, setLang, t: (s, v) => translate(lang, s, v) }), [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export const useI18n = () => useContext(I18nContext);
export const useT = () => useContext(I18nContext).t;
