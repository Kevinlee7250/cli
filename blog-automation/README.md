# 구글 블로그 수익형 자동화

Google Trends 트렌드 키워드 → Claude AI 글 생성 → Blogger 자동 포스팅

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env
# .env 파일을 편집해서 API 키 입력
```

## 설정 순서

### 1. Anthropic API 키
[console.anthropic.com](https://console.anthropic.com) → API Keys → `.env`의 `ANTHROPIC_API_KEY`

### 2. Google Cloud 프로젝트 설정
1. [console.cloud.google.com](https://console.cloud.google.com) 접속
2. 새 프로젝트 생성
3. **Blogger API** 활성화
4. **OAuth 2.0 클라이언트 ID** 생성 (유형: 데스크톱 앱)
5. Client ID, Client Secret을 `.env`에 입력

### 3. 블로그 ID 확인
- Blogger 관리자 → 설정 → 블로그 ID 복사 → `.env`의 `BLOGGER_BLOG_ID`

### 4. Refresh Token 발급 (최초 1회)
```bash
python setup_blogger_auth.py
```
브라우저 인증 후 출력된 Refresh Token을 `.env`에 입력

## 실행

### 즉시 실행 (테스트)
```bash
python main.py --once
```

### 스케줄러 실행 (데몬)
```bash
python main.py
```

### 백그라운드 실행 (Linux)
```bash
nohup python main.py > /dev/null 2>&1 &
```

### systemd 서비스 등록 (서버 운영 시)
```bash
sudo nano /etc/systemd/system/blog-automation.service
```
```ini
[Unit]
Description=Blog Automation

[Service]
WorkingDirectory=/path/to/blog-automation
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now blog-automation
```

## 파일 구조

| 파일 | 역할 |
|------|------|
| `main.py` | 메인 실행 + 스케줄러 |
| `trend_fetcher.py` | Google Trends 키워드 수집 |
| `content_generator.py` | Claude API로 SEO 글 생성 |
| `blogger_uploader.py` | Blogger API 포스팅 |
| `config.py` | 설정 로드 |
| `setup_blogger_auth.py` | OAuth Refresh Token 발급 도우미 |
| `posted_keywords.json` | 중복 포스팅 방지 히스토리 |
| `blog_automation.log` | 실행 로그 |
