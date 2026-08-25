export async function POST(req: Request) {
  if (!process.env.OPENAI_API_KEY) return Response.json({ error: "OPENAI_API_KEY가 설정되지 않았습니다." }, { status: 503 });
  const { title, body } = await req.json() as { title?: string; body?: string };
  if (!title || !body || body.length < 80) return Response.json({ error: "제목과 80자 이상의 본문이 필요합니다." }, { status: 400 });
  const jobs = [
    ["대표 이미지 1장", `Premium editorial blog cover, no text. Topic: ${title}. Clear focal point, 16:9 composition.`],
    ["본문 이미지 1", `Informative editorial photo illustrating the first key idea in this Korean article: ${body.slice(0, 700)}. No text, 3:2.`],
    ["본문 이미지 2", `Distinct complementary editorial photo illustrating another key idea in this Korean article: ${body.slice(700, 1400) || body.slice(0, 700)}. No text, 3:2.`],
    ["요약 인포그래픽 1장", `Clean Korean editorial infographic background for: ${title}. Four visual sections, icons and empty text-safe areas, no readable text, 4:3.`],
  ];
  const outputs = [];
  for (let i = 0; i < jobs.length; i++) {
    const [type, prompt] = jobs[i];
    const res = await fetch("https://api.openai.com/v1/images/generations", { method: "POST", headers: { authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "content-type": "application/json" }, body: JSON.stringify({ model: process.env.OPENAI_IMAGE_MODEL || "gpt-image-2", prompt, size: i === 0 ? "1536x1024" : "1024x1024", quality: "medium", output_format: "webp" }) });
    const json = await res.json() as { data?: { b64_json?: string }[]; error?: { message?: string } };
    if (!res.ok || !json.data?.[0]?.b64_json) return Response.json({ error: json.error?.message || `이미지 ${i + 1} 생성 실패` }, { status: res.status || 502 });
    const slug = title.toLowerCase().replace(/[^a-z0-9가-힣]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "blog-image";
    outputs.push({ id: i, type, alt: i === 0 ? `${title} 대표 이미지` : i === 3 ? `${title} 핵심 요약 인포그래픽` : `${title} 관련 본문 이미지 ${i}`, filename: `${slug}-${["cover","content-1","content-2","summary"][i]}.webp`, image: `data:image/webp;base64,${json.data[0].b64_json}` });
  }
  return Response.json({ assets: outputs });
}
