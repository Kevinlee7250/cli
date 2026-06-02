# 구글 블로그 자동화 설치 스크립트
# 관리자 권한으로 PowerShell 실행 후: powershell -ExecutionPolicy Bypass -File install.ps1

$InstallDir = "I:\blog-automation"
$RepoUrl = "https://raw.githubusercontent.com/Kevinlee7250/cli/claude/gifted-goldberg-5fWHV/blog-automation"
$Files = @(
    "main.py"
    "config.py"
    "trend_fetcher.py"
    "content_generator.py"
    "blogger_uploader.py"
    "setup_blogger_auth.py"
    "requirements.txt"
    ".env.example"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  구글 블로그 자동화 설치 시작" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 설치 폴더 생성
Write-Host "`n[1/5] 설치 폴더 생성: $InstallDir" -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "      폴더 생성 완료" -ForegroundColor Green
} else {
    Write-Host "      폴더 이미 존재함" -ForegroundColor Green
}

# 2. Python 확인 및 설치
Write-Host "`n[2/5] Python 확인 중..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "      Python 발견: $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "      Python이 없습니다. 자동 설치 중..." -ForegroundColor Yellow
    $pythonInstaller = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe" -OutFile $pythonInstaller
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $pythonCmd = "python"
    Write-Host "      Python 설치 완료" -ForegroundColor Green
}

# 3. 파일 다운로드
Write-Host "`n[3/5] 파일 다운로드 중..." -ForegroundColor Yellow
$webClient = New-Object System.Net.WebClient
foreach ($file in $Files) {
    $url = "$RepoUrl/$file"
    $dest = Join-Path $InstallDir $file
    try {
        $webClient.DownloadFile($url, $dest)
        Write-Host "      다운로드: $file" -ForegroundColor Green
    } catch {
        Write-Host "      실패: $file - $_" -ForegroundColor Red
    }
}

# 4. .env 파일 생성
Write-Host "`n[4/5] .env 설정 파일 생성..." -ForegroundColor Yellow
$envFile = Join-Path $InstallDir ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $InstallDir ".env.example") $envFile
    Write-Host "      .env 파일 생성 완료" -ForegroundColor Green
} else {
    Write-Host "      .env 파일 이미 존재함 (덮어쓰지 않음)" -ForegroundColor Green
}

# 5. Python 패키지 설치
Write-Host "`n[5/5] Python 패키지 설치 중..." -ForegroundColor Yellow
$requirementsPath = Join-Path $InstallDir "requirements.txt"
& $pythonCmd -m pip install -r $requirementsPath --quiet
Write-Host "      패키지 설치 완료" -ForegroundColor Green

# 완료 메시지
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  설치 완료!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "다음 단계:" -ForegroundColor White
Write-Host "  1. 메모장으로 .env 파일 열기:" -ForegroundColor White
Write-Host "     notepad $envFile" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. .env에서 아래 항목 입력:" -ForegroundColor White
Write-Host "     ANTHROPIC_API_KEY  = Claude API 키" -ForegroundColor Yellow
Write-Host "     BLOGGER_CLIENT_ID  = Google OAuth 클라이언트 ID" -ForegroundColor Yellow
Write-Host "     BLOGGER_CLIENT_SECRET = Google OAuth 시크릿" -ForegroundColor Yellow
Write-Host "     BLOGGER_BLOG_ID    = 블로그 ID" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3. Blogger 인증 (최초 1회):" -ForegroundColor White
Write-Host "     cd $InstallDir" -ForegroundColor Yellow
Write-Host "     $pythonCmd setup_blogger_auth.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. 테스트 실행:" -ForegroundColor White
Write-Host "     $pythonCmd main.py --once" -ForegroundColor Yellow
Write-Host ""

# .env 파일 자동으로 메모장에서 열기
$open = Read-Host "지금 바로 .env 파일을 편집하시겠습니까? (y/n)"
if ($open -eq "y" -or $open -eq "Y") {
    Start-Process notepad $envFile
}
