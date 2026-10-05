"""테스트 공통 설정 — 네트워크 차단과 `network` 표식.

GitHub Actions 의 「Run tests」 단계(fetch-data · stock-alerts · kakao-daily)가 이 폴더를 그대로 돌린다.
거기서 시세 서버가 느리거나 막혀 있다는 이유로 발송이 멈추면 안 되고, 그 반대로 실제 서버가 준 값에 따라
통과·실패가 갈려도 안 된다. 그래서 테스트는 **네트워크 없이** 돈다.

① 외부 접속 차단 — 루프백(127.0.0.1 · localhost)만 통한다. 이름 풀이나 연결을 시도하면 곧바로 예외가 난다
   (코드가 예외를 삼키고 폴백으로 가는 경로는 그대로 폴백으로 간다). 실측(2026-10-05): 차단한 채로 505건 전부
   통과했고, 접속을 시도한 건 3곳뿐이었다 — test_card_layout(마감 카드의 수급) · test_kakao_cards(주간 카드의
   수급), 둘 다 m.stock.naver.com 이 안 되면 「집계 중」으로 그리는 경로다.
② `@pytest.mark.network` — 진짜 네트워크가 있어야 뜻이 있는 테스트의 표식. 차단을 풀고 돌리되
   CI(`CI` 환경 변수)에서는 건너뛴다. 지금은 표식이 필요한 테스트가 없다.
"""
import os
import socket

import pytest

_LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}
_ALLOW = [False]                                   # network 표식이 붙은 테스트가 도는 동안만 True

_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _is_local(address):
    try:
        host = address[0]
    except (TypeError, IndexError):
        return True
    return host in _LOCAL or str(host).startswith("127.")


def _blocked(target):
    return ConnectionRefusedError(f"테스트는 외부 네트워크를 쓰지 않는다: {target} (필요하면 @pytest.mark.network)")


def _getaddrinfo(host, *args, **kwargs):
    if _ALLOW[0] or host in _LOCAL:
        return _real_getaddrinfo(host, *args, **kwargs)
    raise socket.gaierror(socket.EAI_NONAME, f"테스트는 외부 네트워크를 쓰지 않는다: {host}")


def _connect(self, address):
    if _ALLOW[0] or _is_local(address):
        return _real_connect(self, address)
    raise _blocked(address)


def _connect_ex(self, address):
    if _ALLOW[0] or _is_local(address):
        return _real_connect_ex(self, address)
    return 111                                     # ECONNREFUSED — connect_ex 는 예외 대신 오류 번호를 돌려준다


socket.getaddrinfo = _getaddrinfo
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex


def pytest_configure(config):
    config.addinivalue_line("markers", "network: 실제 네트워크가 있어야 하는 테스트 — 차단을 풀고 돌리며 CI 에서는 건너뜀")


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("CI"):
        return
    skip = pytest.mark.skip(reason="network 표식 — CI 에서는 외부 서버를 부르지 않는다")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _network_policy(request):
    _ALLOW[0] = request.node.get_closest_marker("network") is not None
    yield
    _ALLOW[0] = False
