import { cookies } from "next/headers";

const scope = "openid email profile https://www.googleapis.com/auth/blogger";
const enc = new TextEncoder();

export function googleConfig() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const base = process.env.APP_URL;
  if (!clientId || !clientSecret || !base) throw new Error("Google OAuth 환경변수가 설정되지 않았습니다.");
  return { clientId, clientSecret, redirectUri: `${base.replace(/\/$/, "")}/api/auth/google/callback` };
}

async function key() {
  const secret = process.env.SESSION_SECRET;
  if (!secret) throw new Error("SESSION_SECRET이 설정되지 않았습니다.");
  return crypto.subtle.importKey("raw", await crypto.subtle.digest("SHA-256", enc.encode(secret)), "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function seal(value: unknown) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(), enc.encode(JSON.stringify(value)));
  return `${Buffer.from(iv).toString("base64url")}.${Buffer.from(data).toString("base64url")}`;
}

export async function unseal<T>(value?: string): Promise<T | null> {
  if (!value) return null;
  try {
    const [a, b] = value.split(".");
    const data = await crypto.subtle.decrypt({ name: "AES-GCM", iv: Buffer.from(a, "base64url") }, await key(), Buffer.from(b, "base64url"));
    return JSON.parse(new TextDecoder().decode(data));
  } catch { return null; }
}

export async function authUrl(state: string) {
  const c = googleConfig();
  const q = new URLSearchParams({ client_id: c.clientId, redirect_uri: c.redirectUri, response_type: "code", scope, access_type: "offline", prompt: "consent select_account", include_granted_scopes: "true", state });
  return `https://accounts.google.com/o/oauth2/v2/auth?${q}`;
}

type Tokens = { access_token: string; refresh_token?: string; expires_at: number; email?: string };

export async function tokenFromCookie(): Promise<Tokens | null> {
  const jar = await cookies();
  const token = await unseal<Tokens>(jar.get("google_session")?.value);
  if (!token) return null;
  if (token.expires_at > Date.now() + 60_000) return token;
  if (!token.refresh_token) return null;
  const c = googleConfig();
  const res = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ client_id: c.clientId, client_secret: c.clientSecret, refresh_token: token.refresh_token, grant_type: "refresh_token" }) });
  if (!res.ok) return null;
  const fresh = await res.json() as { access_token: string; expires_in: number };
  return { ...token, access_token: fresh.access_token, expires_at: Date.now() + fresh.expires_in * 1000 };
}

export async function googleFetch(path: string, init?: RequestInit) {
  const token = await tokenFromCookie();
  if (!token) return new Response(JSON.stringify({ error: "Google 로그인이 필요합니다." }), { status: 401, headers: { "content-type": "application/json" } });
  return fetch(`https://www.googleapis.com/blogger/v3${path}`, { ...init, headers: { ...init?.headers, authorization: `Bearer ${token.access_token}`, "content-type": "application/json" } });
}
