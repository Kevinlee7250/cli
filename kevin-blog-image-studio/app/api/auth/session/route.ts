import { tokenFromCookie } from "../../../lib/google";
export async function GET() { const t = await tokenFromCookie(); return Response.json({ connected: !!t, email: t?.email ?? null, openai: !!process.env.OPENAI_API_KEY, googleConfigured: !!(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET && process.env.APP_URL && process.env.SESSION_SECRET) }); }
