from __future__ import annotations

import copy
import json
import pickle

import pytest
from infinity_context_server.memory_comparison_mem0_oss_ingress import (
    Mem0OssIngressCredentialError,
    _consume_mem0_oss_ingress_data_plane,
    _consume_mem0_oss_ingress_probe,
    _consume_mem0_oss_ingress_usage_probe,
    inspect_mem0_oss_ingress_authority,
    issue_mem0_oss_ingress_credential_authority,
)

_RUN_ID = "hosted-canary-1"
_TARGET = "http://127.0.0.1:8888"
_SECRET = "private-ingress-secret"


def test_ingress_authority_is_secret_safe_and_issues_three_exact_scoped_lanes() -> None:
    authority = _authority()
    descriptor = inspect_mem0_oss_ingress_authority(authority)
    rendered = json.dumps({"authority": repr(authority), "descriptor": repr(descriptor)})

    assert _SECRET not in rendered
    assert descriptor.run_id_sha256 != _RUN_ID
    assert _SECRET not in descriptor.credential_binding_id
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(authority)
    with pytest.raises(TypeError):
        copy.copy(authority)

    context = {
        "run_id": _RUN_ID,
        "target_identity_sha256": descriptor.target_identity_sha256,
    }
    assert _consume_mem0_oss_ingress_data_plane(authority, **context) == _SECRET
    assert _consume_mem0_oss_ingress_probe(authority, **context) == _SECRET
    assert _consume_mem0_oss_ingress_usage_probe(authority, **context) == _SECRET
    with pytest.raises(Mem0OssIngressCredentialError, match="context_mismatch"):
        _consume_mem0_oss_ingress_probe(authority, **context)


@pytest.mark.parametrize(
    ("base_url", "hosts"),
    (
        ("http://10.0.0.8:8888", ("10.0.0.8",)),
        ("https://10.0.0.8:8888", ()),
        ("https://93.184.216.34:8888", ("93.184.216.34",)),
        ("http://127.0.0.1:8888", ("127.0.0.2",)),
    ),
)
def test_ingress_authority_rejects_unvetted_or_non_private_targets(
    base_url: str,
    hosts: tuple[str, ...],
) -> None:
    with pytest.raises(Mem0OssIngressCredentialError, match="target_unsafe"):
        issue_mem0_oss_ingress_credential_authority(
            run_id=_RUN_ID,
            base_url=base_url,
            ingress_api_key=_SECRET,
            allowed_target_hosts=hosts,
        )


def test_ingress_authority_accepts_https_private_literal_and_vetted_hostname() -> None:
    private = issue_mem0_oss_ingress_credential_authority(
        run_id=_RUN_ID,
        base_url="https://10.0.0.8:8888",
        ingress_api_key=_SECRET,
        allowed_target_hosts=("10.0.0.8",),
    )
    hosted = issue_mem0_oss_ingress_credential_authority(
        run_id=_RUN_ID,
        base_url="https://mem0.internal.test",
        ingress_api_key=_SECRET,
        allowed_target_hosts=("mem0.internal.test",),
        vetted_transport=_VettedTransport(),
    )

    assert inspect_mem0_oss_ingress_authority(private).target_identity_sha256
    assert inspect_mem0_oss_ingress_authority(hosted).target_identity_sha256


def test_ingress_lane_mismatch_is_terminal_and_never_reflects_inputs() -> None:
    authority = _authority()
    descriptor = inspect_mem0_oss_ingress_authority(authority)

    with pytest.raises(Mem0OssIngressCredentialError) as caught:
        _consume_mem0_oss_ingress_data_plane(
            authority,
            run_id="other-run",
            target_identity_sha256=descriptor.target_identity_sha256,
        )
    with pytest.raises(Mem0OssIngressCredentialError):
        _consume_mem0_oss_ingress_data_plane(
            authority,
            run_id=_RUN_ID,
            target_identity_sha256=descriptor.target_identity_sha256,
        )
    assert _SECRET not in repr(caught.value)
    assert "other-run" not in repr(caught.value)


def _authority():
    return issue_mem0_oss_ingress_credential_authority(
        run_id=_RUN_ID,
        base_url=_TARGET,
        ingress_api_key=_SECRET,
        allowed_target_hosts=("127.0.0.1",),
    )


class _VettedTransport:
    def open_client(self, *, base_url: str, timeout_seconds: float):
        raise AssertionError((base_url, timeout_seconds))
