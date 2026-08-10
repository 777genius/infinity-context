from __future__ import annotations

import hashlib


class StreamingResponse:
    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        fail_if_third_chunk_is_read: bool = False,
    ) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.chunks = chunks
        self.fail_if_third_chunk_is_read = fail_if_third_chunk_is_read
        self.chunk_reads = 0
        self.content_reads = 0

    @property
    def content(self) -> bytes:
        self.content_reads += 1
        raise AssertionError("streaming preflight must not materialize response.content")

    def __enter__(self) -> StreamingResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def iter_raw(self, *, chunk_size: int):
        assert chunk_size == 8_192
        for index, chunk in enumerate(self.chunks):
            self.chunk_reads += 1
            if self.fail_if_third_chunk_is_read and index == 2:
                raise AssertionError("stream read continued after the response exceeded 32 KiB")
            yield chunk


class StreamingClient:
    def __init__(self, response: StreamingResponse) -> None:
        self.response = response
        self.init_kwargs: dict[str, object] = {}
        self.stream_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def construct(self, **kwargs: object) -> StreamingClient:
        self.init_kwargs = kwargs
        return self

    def __enter__(self) -> StreamingClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("runtime attestation must use bounded streaming")

    def stream(self, *args: object, **kwargs: object) -> StreamingResponse:
        self.stream_calls.append((args, kwargs))
        return self.response


def runtime_attestation_request() -> dict[str, object]:
    return {
        "probe_nonce_sha256": _sha("streaming-probe"),
        "run_id_sha256": _sha("streaming-run"),
        "schema_version": "mem0-oss-adapter-v5.runtime-attestation-request.v1",
        "target_origin_sha256": _sha("streaming-target"),
        "validity_seconds": 60,
    }


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


__all__ = ("StreamingClient", "StreamingResponse", "runtime_attestation_request")
