import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { googleConfig, seal } from "../../../../lib/google";
export async function GET(req: Request) {
  const url = new URL(req.url); const jar = await cookies();
  if (!url.searchParams.get("code") || url.searchParams.get("state") !== jar.get("oauth_state")?.value) return NextResponse.json({ error: "잘못된 OAuth 응답입니다." }, { status: 400 });
  const c = googleConfig();
  const res = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ code: url.searchParams.get("code")!, client_id: c.clientId, client_secret: c.clientSecret, redirect_uri: c.redirectUri, grant_type: "authorization_code" }) });
  if (!res.ok) return NextResponse.json({ error: "Google 토큰 교환에 실패했습니다." }, { status: 502 });
  const t = await res.json() as { access_token: string; refresh_token?: string; expires_in: number };
  const info = await fetch("https://www.googleapis.com/oauth2/v2/userinfo", { headers: { authorization: `Bearer ${t.access_token}` } }).then(r => r.json()) as { email?: string };
  jar.set("google_session", await seal({ ...t, email: info.email, expires_at: Date.now() + t.expires_in * 1000 }), { httpOnly: true, secure: true, sameSite: "lax", maxAge: 60 * 60 * 24 * 30, path: "/" });
  jar.delete("oauth_state"); return NextResponse.redirect(c.redirectUri.replace("/api/auth/google/callback", "/?connected=1"));
}
