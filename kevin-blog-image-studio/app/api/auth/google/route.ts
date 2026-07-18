import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { authUrl } from "../../../lib/google";
export async function GET() {
  const state = crypto.randomUUID();
  const jar = await cookies();
  jar.set("oauth_state", state, { httpOnly: true, secure: true, sameSite: "lax", maxAge: 600, path: "/" });
  try { return NextResponse.redirect(await authUrl(state)); }
  catch (e) { return NextResponse.json({ error: e instanceof Error ? e.message : "OAuth 설정 오류" }, { status: 503 }); }
}
