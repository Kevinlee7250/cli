# -*- coding: utf-8 -*-
"""백업 파일로 경험 주장 감사를 로컬에서 돌립니다 (Blogger API 호출 없음).

탐지 규칙을 손볼 때 워크플로를 기다리면 한 번에 몇 분씩 걸리고, 그 사이
무엇이 좋아졌는지 비교하기 어렵습니다. backup_live_posts.py가 남긴 스냅샷에
같은 규칙을 적용하면 즉시 결과가 나옵니다.

  python backup_live_posts.py            # 먼저 백업을 만들고
  python audit_from_backup.py            # 요약만
  python audit_from_backup.py -v         # 지적된 문장까지
"""
import glob, io, json, collections, sys
from experience_audit import analyze_text, _strip_html
from title_policy import check_title

path = sorted(glob.glob('backups/live_posts_*.json'))[-1]
data = json.load(io.open(path, encoding='utf-8'))
posts = data if isinstance(data, list) else (data.get('posts') or data.get('items') or [])
print('백업:', path, '| 글', len(posts))

flagged = []
lab = collections.Counter()
for p in posts:
    title = p.get('title') or ''
    body = _strip_html(p.get('content') or '')
    th = check_title(title)
    bh = analyze_text(body)
    if th or bh:
        flagged.append((p, th, bh))
        for h in bh:
            lab[h['label']] += 1
        for t in th:
            lab['[제목] ' + str(t)] += 1

print('지적:', len(flagged), '/', len(posts))
for k, v in lab.most_common():
    print(' ', v, k)
if '-v' in sys.argv:
    print('--- 상세 ---')
    for p, th, bh in flagged:
        print('*', (p.get('title') or '')[:52], ('| 제목:' + str(th)) if th else '')
        for h in bh[:3]:
            print('    -', h['severity'], h['label'], '|', h['excerpt'][:100].replace('\n', ' '))
