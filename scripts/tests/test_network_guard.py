"""conftest.py 의 네트워크 차단이 살아 있는지 — 누가 conftest 를 고쳐 차단이 풀려도 CI 가 모르고 지나가지 않게."""
import socket
import threading

import pytest


def test_name_lookup_of_an_external_host_is_refused():
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("m.stock.naver.com", 443)


def test_connecting_to_an_external_address_is_refused():
    s = socket.socket()
    try:
        with pytest.raises(ConnectionRefusedError):
            s.connect(("203.0.113.7", 80))                     # TEST-NET-3 — 어차피 닿지 않는 주소
        assert s.connect_ex(("203.0.113.7", 80)) == 111
    finally:
        s.close()


def test_loopback_still_works():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    t = threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True)
    t.start()
    try:
        c = socket.create_connection(("localhost", port), timeout=5)
        c.close()
    finally:
        t.join(5)
        srv.close()


@pytest.mark.network
def test_network_marker_lifts_the_block():
    # 표식이 붙은 테스트에서는 이름 풀이가 실제 풀이기로 간다(CI 에서는 이 테스트 자체를 건너뛴다).
    # .invalid 는 어디서도 풀리지 않는 이름이라 결과는 실패지만, 그 실패가 우리 차단 예외가 아니어야 한다.
    try:
        socket.getaddrinfo("example.invalid", 80)
    except socket.gaierror as e:
        assert "외부 네트워크를 쓰지 않는다" not in str(e)
