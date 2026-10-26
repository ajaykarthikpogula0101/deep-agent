// Type declarations for robin-widget (the Champ Robin chat widget). The widget itself is plain JavaScript with no
// dependencies; these types let TypeScript projects (Angular, React, Vue, Svelte, Next.js...) use it.

/** 'peek' (the retired compact card) is still accepted and opens 'half'. */
export type RobinMode = 'hidden' | 'half' | 'full' | 'peek';
export type RobinScheme = 'light' | 'dark' | 'auto';
export type RobinTextSize = 's' | 'm' | 'l';

/** One piece of a reply: text, buttons, lead_form, time_slots, card, confirmation, error or files. */
/** One UI block: text, buttons, lead_form, time_slots, card, confirmation, error, files or ui_card (an answer card). */
export interface RobinBlock {
  type: string;
  [key: string]: unknown;
}

export interface RobinReply {
  /** The UI blocks to show; a reply with only `text` shows it as one text block. */
  blocks?: RobinBlock[];
  text?: string;
  /** The backend's id for this answer, sent back with 👍 / 👎 (adapter.feedback). */
  ref?: string | number | null;
  /** A conversation title, or a promise of one, applied when it arrives. */
  title?: string | Promise<string | null> | null;
}

/** What the visitor sent: a typed message, or an action (a starter, a button, a form, a chosen slot). */
export interface RobinInput {
  type: 'message' | 'action';
  text?: string;
  name?: string;
  value?: string;
  label?: string;
  data?: unknown;
  via?: 'text' | 'voice';
  /** Sent for the visitor (an email link's question), not typed. */
  auto?: boolean;
  attachments?: Array<{ id: string; name: string; size: number; type: string }>;
}

export interface RobinPayload {
  conversationId: string;
  visitor: Record<string, unknown>;
  input: RobinInput;
  history: Array<{ role: 'user' | 'bot'; text: string }>;
  page: { url: string; title: string };
  files: File[];
}

export interface RobinSendOptions {
  signal?: AbortSignal;
  /** Report a step ("Searching the docs…"); the loader shows it. */
  onStatus?: (text: string) => void;
  /** Stream the answer's text as it grows. */
  onText?: (text: string) => void;
}

export interface RobinAdapter {
  send(payload: RobinPayload, options?: RobinSendOptions): Promise<RobinReply>;
  /** Optional hooks a richer backend can offer; the widget uses each one only when it is there. */
  setup?(): Promise<unknown>;
  feedback?(ref: string | number | null, value: 'up' | 'down' | null, conversationId: string, note?: string): void;
  conversations?(): Promise<unknown[]>;
  conversation?(conversationId: string): Promise<unknown[] | null>;
  markRead?(conversationId: string): void;
  rename?(conversationId: string, title: string): Promise<unknown>;
  bookings?(): Promise<unknown[]>;
  /** Seconds on the page and how far it is scrolled (0-100): the pop-up a backend's rules choose, if any. */
  outreach?(dwellSeconds: number, scrollPercent: number): Promise<unknown>;
  outreachOpened?(eventId: number): void;
  outreachDismissed?(eventId: number): void;
  claim?(claim: unknown, conversationId: string): Promise<unknown>;
  claimed?(booking: unknown): void;
  gifs?(query: string): Promise<unknown[]>;
  speak?(text: string): Promise<Blob>;
  transcribe?(audio: Blob, lang?: string): Promise<unknown>;
  schedulerLink?(): Promise<string | null>;
  /** An email link's token read from the page's #fragment (deep-agent), once at start. */
  claimToken?(): { token: string; q: string | null } | null;
  cardRenderer?(): Promise<unknown>;
  setToken?(token: string | null): Promise<unknown>;
}

export interface RobinStarter {
  label: string;
  value: string;
  icon?: string;
}

export interface RobinEvent {
  type: string;
  at: string;
  [key: string]: unknown;
}

export interface RobinConfig {
  appName?: string;
  companyName?: string;
  primaryColor?: string;
  position?: 'right' | 'left';
  colorScheme?: RobinScheme;
  attachments?: { accept?: string; maxFiles?: number; maxSizeMB?: number } | boolean;
  emoji?: boolean;
  dictation?: boolean;
  voice?: boolean;
  voiceLanguages?: string[];
  privacyUrl?: string | null;
  loadFonts?: boolean;
  openingTransition?: boolean;
  thinkingOverlay?: boolean;
  motion?: 'auto' | 'full' | 'reduce';
  greeting?: string;
  intro?: string;
  placeholder?: string;
  thinkingText?: string;
  disclaimer?: string;
  starters?: RobinStarter[];
  teaser?: { text: string; delay?: number } | null;
  initialMode?: RobinMode;
  adapter?: RobinAdapter | null;
  endpoint?: string | null;
  /** URL of a deep-agent server: answers (streamed, with sources), booking and hand-over come from it. */
  deepAgent?: string | null;
  /** An external booking page offered in Help & contact (a deep-agent server supplies its own). */
  schedulerUrl?: string | null;
  /** deep-agent: a signed-in visitor's token, minted by your server (sent as X-Visitor-Token). */
  visitorToken?: string | null;
  /** deep-agent: unverified name / email hints for a visitor without a token. */
  userName?: string | null;
  userEmail?: string | null;
  headers?: Record<string, string>;
  onEvent?: ((event: RobinEvent) => void) | null;
  persist?: boolean;
  zIndex?: number;
}

/** The running widget (Robin.instance). Its methods are internal; use the Robin API instead. */
export interface RobinInstance {
  cfg: Required<RobinConfig>;
  mode: RobinMode;
  view: string;
}

export interface RobinApi {
  readonly version: string;
  /** Mounts the widget (replacing any earlier one). Call it in the browser, e.g. in a mount hook. */
  init(config?: RobinConfig): RobinInstance | null;
  open(mode?: RobinMode): void;
  close(): void;
  toggle(): void;
  expand(): void;
  collapse(): void;
  setWide(on: boolean): void;
  ask(text: string): void;
  voice(): void;
  endVoice(): void;
  /** Retired: Robin always shows the swallow. Kept so older embeds don't break. */
  setTheme(theme?: string): void;
  setScheme(scheme: RobinScheme): void;
  /** A #rrggbb colour, or null for the default look. */
  setBrand(color: string | null): void;
  setTextSize(size: RobinTextSize): void;
  setReduceMotion(on: boolean): void;
  /** deep-agent: a signed-in visitor's token (null signs out); /me is asked again and forms prefill. */
  setToken(token: string | null): Promise<unknown> | void;
  on(type: string, handler: (event: RobinEvent) => void): RobinApi;
  reset(): void;
  /** Removes the widget from the page. Call it on unmount. */
  destroy(): void;
  readonly instance: RobinInstance | null;
  HttpAdapter: new (endpoint: string, headers?: Record<string, string>) => RobinAdapter;
  DeepAgentAdapter: new (baseUrl: string, config?: RobinConfig) => RobinAdapter;
}

declare const Robin: RobinApi;
export default Robin;

declare global {
  interface Window {
    Robin: RobinApi;
    /** Set before the script loads to boot the widget on its own. */
    RobinSettings?: RobinConfig;
  }
}
