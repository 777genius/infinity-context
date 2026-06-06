"""FastAPI dependency helpers."""

from fastapi import Request

from memo_stack_server.composition import Container


def get_container(request: Request) -> Container:
    return request.app.state.container
