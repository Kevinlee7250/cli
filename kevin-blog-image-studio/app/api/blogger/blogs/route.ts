import { googleFetch } from "../../../lib/google";
export async function GET() { const r = await googleFetch("/users/self/blogs"); return new Response(r.body, { status: r.status, headers: { "content-type": "application/json" } }); }
