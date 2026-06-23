import niquests
from urllib3 import Retry, Timeout

session = niquests.Session(
    timeout=Timeout(connect=15, read=30),
    retries=Retry(
        connect=5,
        read=3,
        other=3,
        backoff_factor=0.2,
        backoff_jitter=0.5,
        status_forcelist={403, 429, 500, 502, 503, 504},
        raise_on_status=True,
    ),
)


def head(
    url: str, *, allow_redirects: bool = False, stream: bool | None = None
) -> niquests.Response:
    return session.head(url, allow_redirects=allow_redirects, stream=stream).raise_for_status()


def get(
    url: str, *, allow_redirects: bool = True, stream: bool | None = None
) -> niquests.Response:
    return session.get(url, allow_redirects=allow_redirects, stream=stream).raise_for_status()
