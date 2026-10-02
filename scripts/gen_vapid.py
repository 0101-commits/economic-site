#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""웹 푸시 VAPID 키 한 쌍 + 발송기 읽기 키를 만들어 화면에만 보여 준다. 파일로 저장하지 않는다.

실행: python scripts/gen_vapid.py
출력된 명령을 저장소 루트에서 그대로 실행한다(bash). 값은 --body 로 넘긴다 — 클립보드·PowerShell 파이프는
UTF-8 BOM 이 끼어 키가 깨진 전례가 있다. 화면을 닫으면 값은 어디에도 남지 않으니 등록을 마친 뒤 닫는다.

  VAPID_PUBLIC_KEY   공개키(base64url, 65바이트 비압축 점) — Worker 시크릿(/push/key 가 브라우저에 준다)
  VAPID_PRIVATE_KEY  개인키(base64url, 32바이트) — GitHub 시크릿(scripts/send_push.py 만 쓴다)
  VAPID_SUBJECT      연락처 mailto: — GitHub 시크릿. 푸시 서비스가 문제 있을 때 연락하는 주소
  PUSH_READ_KEY      발송기가 Worker 에서 구독 목록을 읽는 키 — Worker 시크릿과 GitHub 시크릿 두 곳에 같은 값

키를 바꾸면 기존 구독은 전부 무효가 된다(기기마다 「폰 알림」을 다시 켜야 한다).
"""
import base64
import secrets
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_keys():
    """(공개키, 개인키) — 둘 다 base64url(패딩 없음). npx web-push generate-vapid-keys 와 같은 형식."""
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(pub), b64u(k.private_numbers().private_value.to_bytes(32, "big"))


def main():
    pub, priv = make_keys()
    read = secrets.token_urlsafe(32)
    subject = sys.argv[1] if len(sys.argv) > 1 else "mailto:<연락받을 주소>"
    print("# 1) GitHub Actions 시크릿 (저장소 루트에서)")
    print(f"gh secret set VAPID_PRIVATE_KEY --body='{priv}'")
    print(f"gh secret set VAPID_SUBJECT --body='{subject}'")
    print(f"gh secret set PUSH_READ_KEY --body='{read}'")
    print()
    print("# 2) Worker 시크릿 (저장소 루트에서, bash — printf 는 개행을 붙이지 않는다)")
    print(f"printf %s '{pub}' | npx wrangler secret put VAPID_PUBLIC_KEY")
    print(f"printf %s '{read}' | npx wrangler secret put PUSH_READ_KEY")
    print()
    print("# 값은 저장되지 않았다. 위 명령을 실행한 뒤 이 화면을 닫는다.")
    if subject.startswith("mailto:<"):
        print("# VAPID_SUBJECT 는 실제 주소로 바꿔 넣는다: python scripts/gen_vapid.py mailto:you@example.com")


if __name__ == "__main__":
    main()
