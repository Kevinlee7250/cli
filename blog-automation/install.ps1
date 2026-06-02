$InstallDir = "I:\blog-automation"
$RepoUrl = "https://raw.githubusercontent.com/Kevinlee7250/cli/claude/gifted-goldberg-5fWHV/blog-automation"
$Files = "main.py","config.py","trend_fetcher.py","content_generator.py","blogger_uploader.py","setup_blogger_auth.py","requirements.txt",".env.example"

Write-Host "=== 구글 블로그 자동화 설치 시작 ===" -ForegroundColor Cyan

# 1. 폴더 생성
Write-Host "[1/5] 폴더 생성..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Write-Host "      완료: $InstallDir" -ForegroundColor Green

# 2. Python 확인
Write-Host "[2/5] Python 확인..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in "python","python3","py") {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "      발견: $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "      Python 없음. 설치 중 (약 2분 소요)..." -ForegroundColor Yellow
    $installer = "$env:TEMP\python-installer.exe"
    (New-Object System.Net.WebClient).DownloadFile("https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe", $installer)
    Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine")
    $pythonCmd = "python"
    Write-Host "      Python 설치 완료" -ForegroundColor Green
}

# 3. 파일 다운로드
Write-Host "[3/5] 파일 다운로드..." -ForegroundColor Yellow
$wc = New-Object System.Net.WebClient
foreach ($f in $Files) {
    $dest = Join-Path $InstallDir $f
    try {
        $wc.DownloadFile("$RepoUrl/$f", $dest)
        Write-Host "      OK: $f" -ForegroundColor Green
    } catch {
        Write-Host "      FAIL: $f" -ForegroundColor Red
    }
}

# 4. .env 생성
Write-Host "[4/5] .env 파일 생성..." -ForegroundColor Yellow
$envSrc = Join-Path $InstallDir ".env.example"
$envDst = Join-Path $InstallDir ".env"
if (-not (Test-Path $envDst)) {
    Copy-Item $envSrc $envDst
    Write-Host "      .env 생성 완료" -ForegroundColor Green
} else {
    Write-Host "      .env 이미 존재 (유지)" -ForegroundColor Green
}

# 5. 패키지 설치
Write-Host "[5/5] Python 패키지 설치..." -ForegroundColor Yellow
$req = Join-Path $InstallDir "requirements.txt"
& $pythonCmd -m pip install -r $req --quiet
Write-Host "      완료" -ForegroundColor Green

Write-Host ""
Write-Host "=== 설치 완료! ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "다음 단계:" -ForegroundColor White
Write-Host "  1. 메모장으로 .env 열기:" -ForegroundColor White
Write-Host "     notepad $envDst" -ForegroundColor Yellow
Write-Host "  2. API 키 4개 입력 후 저장" -ForegroundColor White
Write-Host "  3. Blogger 인증:" -ForegroundColor White
Write-Host "     cd $InstallDir" -ForegroundColor Yellow
Write-Host "     $pythonCmd setup_blogger_auth.py" -ForegroundColor Yellow
Write-Host "  4. 테스트:" -ForegroundColor White
Write-Host "     $pythonCmd main.py --once" -ForegroundColor Yellow
Write-Host ""

notepad $envDst
