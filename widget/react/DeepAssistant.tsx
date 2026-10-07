"use client";
/**
 * <DeepAssistant /> — React/Next.js wrapper around the <deep-assistant> web component.
 *
 * Drop this file into your app (ChampSet: frontend/components/DeepAssistant.tsx) and render it once, for
 * example in app/layout.tsx next to <HelpButton />:
 *
 *   <DeepAssistant api={process.env.NEXT_PUBLIC_ASSISTANT_URL!} mode="launcher" />
 *
 * Identity: with Clerk, the wrapper passes the user's session JWT to the assistant (refreshed every 50 s,
 * Clerk tokens live 60 s). The assistant verifies it against your Clerk JWKS when CLERK_JWT_ISSUER_DOMAIN is
 * set on the assistant server. Without Clerk, pass `token` yourself (an HMAC token minted by your backend) or
 * `userName` / `userEmail` as unverified prefill hints.
 */
import { useEffect, useRef, type CSSProperties } from "react";

type Props = {
  api: string;                       // assistant base URL, e.g. https://assistant.deependhq.com
  mode?: "panel" | "launcher";
  theme?: "auto" | "dark" | "light";
  title?: string;
  subtitle?: string;
  suggestions?: string[];
  token?: string;                    // explicit token (HMAC or JWT); overrides Clerk
  useClerk?: boolean;                // default true when @clerk/nextjs is available
  userName?: string;
  userEmail?: string;
  open?: boolean;
  style?: CSSProperties;
  className?: string;
  onAnswer?: (d: { question: string; answer: string; sources: { n: number; url: string; title?: string }[]; messageId: number | null; failed: boolean }) => void;
  onBooking?: (d: { status: string; leadId: number | null; handoffUrl: string | null }) => void;
  onHandover?: (d: { leadId: number; email: string; briefSent: boolean }) => void;
  onFeedback?: (d: { messageId: number; rating: 1 | -1; note: string | null }) => void;
};

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "deep-assistant": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & Record<string, unknown>;
    }
  }
}

type AssistantElement = HTMLElement & { setToken(t: string | null): void; ask(t: string): void; open(): void; close(): void; reset(): void };

let clerkHook: null | (() => { isSignedIn?: boolean; getToken: () => Promise<string | null> }) = null;
try {
  // Optional dependency: resolved at build time in apps that have Clerk, ignored elsewhere.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  clerkHook = require("@clerk/nextjs").useAuth;
} catch { clerkHook = null; }

export function DeepAssistant({ api, mode = "launcher", theme = "auto", title, subtitle, suggestions, token, useClerk = true, userName, userEmail, open, style, className,
  onAnswer, onBooking, onHandover, onFeedback }: Props) {
  const ref = useRef<AssistantElement>(null);
  const auth = useClerk && clerkHook ? clerkHook() : null;

  // load the component from the assistant server once (no bundling, no version drift)
  useEffect(() => {
    if (customElements.get("deep-assistant")) return;
    const s = document.createElement("script"); s.type = "module"; s.src = `${api.replace(/\/+$/, "")}/static/deep-assistant.js`; document.head.appendChild(s);
  }, [api]);

  // identity: explicit token wins; else Clerk session token, refreshed before it expires
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (token) { el.setAttribute("token", token); return; }
    if (!auth || !auth.isSignedIn) { el.removeAttribute("token"); return; }
    let alive = true;
    const refresh = async () => { try { const t = await auth.getToken(); if (alive && t) el.setAttribute("token", t); } catch { /* keep the previous token */ } };
    refresh(); const id = setInterval(refresh, 50_000);
    return () => { alive = false; clearInterval(id); };
  }, [token, auth?.isSignedIn, auth]);

  useEffect(() => {
    const el = ref.current; if (!el) return;
    const h = {
      "deep-assistant:answer": (e: Event) => onAnswer?.((e as CustomEvent).detail),
      "deep-assistant:booking": (e: Event) => onBooking?.((e as CustomEvent).detail),
      "deep-assistant:handover": (e: Event) => onHandover?.((e as CustomEvent).detail),
      "deep-assistant:feedback": (e: Event) => onFeedback?.((e as CustomEvent).detail),
    };
    Object.entries(h).forEach(([k, f]) => el.addEventListener(k, f));
    return () => Object.entries(h).forEach(([k, f]) => el.removeEventListener(k, f));
  }, [onAnswer, onBooking, onHandover, onFeedback]);

  useEffect(() => { const el = ref.current; if (!el) return; if (open) el.setAttribute("open", ""); else if (open === false) el.removeAttribute("open"); }, [open]);

  return (
    <deep-assistant ref={ref} api={api} mode={mode} theme={theme} title={title} subtitle={subtitle} suggestions={suggestions?.join("|")}
      user-name={userName} user-email={userEmail} style={style} className={className} />
  );
}

export default DeepAssistant;
