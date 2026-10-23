import sys
import time
from typing import Any

import niquests
from urllib3 import AsyncHTTPResponse, HTTPResponse, Retry, Timeout


class LoggingRetry(Retry):
    def sleep(self, response: HTTPResponse | None = None) -> None:
        if self.respect_retry_after_header and response:
            retry_after = self.get_retry_after(response)
            if retry_after:
                print(f"Will retry after {retry_after:.2f} seconds", file=sys.stderr)
                time.sleep(retry_after)
                return

        backoff = self.get_backoff_time()
        if backoff <= 0:
            return
        print(f"Backing off for {backoff:.2f} seconds", file=sys.stderr)
        time.sleep(backoff)

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: HTTPResponse | AsyncHTTPResponse | None = None,
        error: Exception | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Retry:
        new_retry = super().increment(method, url, response, error, *args, **kwargs)
        print(f"Retrying due to following error: {error!r}", file=sys.stderr)
        return new_retry


session = niquests.Session(
    timeout=Timeout(connect=30, read=30),
    retries=LoggingRetry(
        connect=8,
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
