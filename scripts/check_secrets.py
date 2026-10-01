#!/usr/bin/env python3
"""커밋 전 비밀값 검사 (파이썬 표준 라이브러리만 사용).

기본: 스테이징된 파일(git diff --cached, ACM)의 스테이징 내용을 검사한다.
--all: 추적 중인 전체 파일을 디스크 내용 기준으로 검사한다.
위반이 있으면 파일:줄 + 종류를 출력하고 exit 1. 값은 앞뒤 4자만 보여 준다.
오탐 예외: 해당 줄 끝에 `# secret-ok` (또는 `// secret-ok`) 주석.
"""
import fnmatch
import re
import subprocess
import sys

# Windows 콘솔(cp949)에서 우리말 메시지가 깨지거나 쓰기 자체가 실패하지 않도록 출력을 UTF-8 로 고정
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 파일 이름만으로 위반 (내용과 무관). .env.example 류는 견본이라 허용.
NAME_PATTERNS = ["*.key", "*.key.txt", "*.pem", "*동기화키*", ".env*", "*.dev.vars"]
NAME_ALLOW = [".env.example", ".env.sample", ".env.template"]

# 내용 검사 허용 목록: 봇 산출물·의존성은 건너뛴다 (파일 이름 검사는 그대로 적용).
CONTENT_SKIP_DIRS = ("node_modules/", "bundles/")
CONTENT_SKIP_NAMES = ("data.json",)  # 봇이 커밋하는 대용량 산출물
CONTENT_SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2",
                    ".ttf", ".zip", ".gz", ".pdf", ".mp3", ".mp4", ".min.js")

LINE_RULES = [
    ("개인키 PEM", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub 토큰", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    ("GitHub PAT", re.compile(r"github_pat_\w{22,}")),
    ("AWS 액세스 키", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack 토큰", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Discord 웹훅", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]+")),
    ("Bearer 토큰 리터럴", re.compile(r"Bearer [A-Za-z0-9_-]{30,}")),
    # 이름 옆에 32자 이상 리터럴이 있고 숫자가 하나라도 섞인 경우 (hex/base64 근사)
    ("비밀 이름 옆 긴 리터럴", re.compile(
        r"""(?i)(?:key|secret|token|password|passphrase)\w*["']?\s*[:=]\s*["']((?=[^"']*\d)[A-Za-z0-9+/=_-]{32,})["']""")),
]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def mask(v):
    return v if len(v) <= 8 else v[:4] + "..." + v[-4:]


def name_violation(path):
    base = path.rsplit("/", 1)[-1]
    if base in NAME_ALLOW:
        return None
    for p in NAME_PATTERNS:
        if fnmatch.fnmatch(base, p):
            return f"비밀 파일 이름 ({p})"
    return None


def skip_content(path):
    base = path.rsplit("/", 1)[-1]
    return (any(path.startswith(d) or "/" + d in path for d in CONTENT_SKIP_DIRS)
            or base in CONTENT_SKIP_NAMES or path.endswith(CONTENT_SKIP_EXT))


def scan_text(path, text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if "secret-ok" in line:
            continue
        for kind, rx in LINE_RULES:
            m = rx.search(line)
            if m:
                out.append((path, n, kind, mask(m.group(m.lastindex or 0))))
    return out


def main():
    scan_all = "--all" in sys.argv[1:]
    if scan_all:
        names = git("ls-files", "-z").split(b"\0")
    else:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z").split(b"\0")
    found = []
    for raw in names:
        if not raw:
            continue
        path = raw.decode("utf-8", "replace")
        why = name_violation(path)
        if why:
            found.append((path, 0, why, "-"))
        if skip_content(path):
            continue
        try:
            data = open(path, "rb").read() if scan_all else git("show", ":" + path)
        except (OSError, subprocess.CalledProcessError):
            continue
        if b"\0" in data[:8192]:  # 바이너리
            continue
        found += scan_text(path, data.decode("utf-8", "replace"))
    for path, n, kind, val in found:
        loc = f"{path}:{n}" if n else path
        print(f"[비밀 의심] {loc}  {kind}  {val}")
    if found:
        print(f"\n{len(found)}건 발견. 오탐이면 줄 끝에 '# secret-ok' 를 붙이세요.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
