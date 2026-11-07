"""PR #108의 블로그 발행 워크플로를 외부 API 호출 없이 검증합니다.

- .env heredoc을 더미 값으로 치환해 python-dotenv로 실제 파싱합니다.
- Python 명령을 Bash 함수로 대체해 글 게시 없이 CLI 인자만 수집합니다.
- 3개 블로그 모두 별도로 확인합니다.
"""
from io import StringIO
from pathlib import Path
import logging
import os
import re
import subprocess

import pytest
import yaml
from dotenv import dotenv_values


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "blog-run.yml"
BLOGS = ("blog1", "blog2", "blog3")
GITHUB_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


@pytest.fixture(scope="module")
def jobs():
    with WORKFLOW.open(encoding="utf-8") as f:
        definition = yaml.safe_load(f)
    return definition["jobs"]


def _step(jobs, blog, label):
    return next(
        s for s in jobs[f"publish-{blog}"]["steps"]
        if s.get("name") == label
    )["run"]


@pytest.mark.parametrize("blog", BLOGS)
def test_env_heredoc_is_valid_dotenv(jobs, blog, caplog):
    script = _step(jobs, blog, ".env 파일 생성")
    match = re.search(r"(?ms)^cat > \.env << 'ENVEOF'\n(.*?)^ENVEOF\s*$", script)
    assert match, f"{blog}: ENVEOF 블록이 없거나 경계가 잘못되었습니다"
    lines = [line.strip() for line in match.group(1).splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    assert len(lines) >= 25, f"{blog}: 환경변수가 예상보다 적습니다"
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*=(?:\"[^\n\"]*\"|'[^\n']*'|[^\"'\n]*)", line)
               for line in lines), f"{blog}: .env에 잘못된 형식이나 쉘 코드가 있습니다"

    keys = [line.split("=", 1)[0] for line in lines]
    assert len(keys) == len(set(keys)), f"{blog}: 환경변수 중복 선언"
    # 실제 비밀 값 없이 파서가 전체 행을 정상 인식하는지 검증
    fake_env = GITHUB_EXPR.sub("SAFE_TEST_VALUE", match.group(1))
    with caplog.at_level(logging.WARNING, logger="dotenv.main"):
        parsed = dotenv_values(stream=StringIO(fake_env), interpolate=False)
    assert set(parsed) == set(keys), f"{blog}: dotenv 파싱 중 누락 발생"
    assert not any("could not parse" in item.message for item in caplog.records)


def _mock_cli(jobs, blog, article_type, mode, keyword, tmp_path):
    script = _step(jobs, blog, f"{blog} 게시")

    def interpolate(match):
        expr = match.group(1).strip()
        if expr.startswith("inputs.article_type"):
            return article_type
        if expr.startswith("inputs.mode"):
            return mode
        if expr.startswith("inputs.keyword"):
            return keyword
        if expr.startswith("inputs.series_count"):
            return "4"
        if expr.startswith("inputs.series_type"):
            return "auto"
        if expr.startswith("inputs.start_episode"):
            return "1"
        return ""

    script = GITHUB_EXPR.sub(interpolate, script)
    capture = tmp_path / "args.txt"
    env = dict(os.environ, CAPTURE_FILE=str(capture))
    # 진짜 python 실행을 가로채므로 Blogger/API/파일 쓰기를 발생시키지 않습니다.
    bash = "python() { printf '%s\\n' \"$@\" > \"$CAPTURE_FILE\"; }\n" + script
    result = subprocess.run(
        ["bash", "-e", "-c", bash],
        env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert capture.exists(), f"{blog}: main.py 명령이 호출되지 않았습니다"
    return capture.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("blog", BLOGS)
@pytest.mark.parametrize("article_type", ("auto", "how_to", "news_analysis"))
@pytest.mark.parametrize("keyword", ("", "test-article"))
def test_live_cli_passes_article_type_without_publishing(
    jobs, blog, article_type, keyword, tmp_path
):
    args = _mock_cli(jobs, blog, article_type, "live", keyword, tmp_path)
    assert args[:2] == ["main.py", "--once"]
    assert ["--blog", blog] == args[2 + (2 if keyword else 0):4 + (2 if keyword else 0)]
    if keyword:
        assert args[2:4] == ["--keyword", keyword]
    if article_type == "auto":
        assert "--article-type" not in args
    else:
        assert args[-2:] == ["--article-type", article_type]


@pytest.mark.xfail(
    strict=True,
    reason="기존 mode=test 분기는 --article-type을 전달하지 않고 main.py의 --test 분기도 override를 적용하지 않음",
)
@pytest.mark.parametrize("blog", BLOGS)
def test_mode_test_can_verify_article_type_after_followup_fix(jobs, blog, tmp_path):
    args = _mock_cli(jobs, blog, "how_to", "test", "test-article", tmp_path)
    assert args[-2:] == ["--article-type", "how_to"]
