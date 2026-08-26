from __future__ import annotations

import json
from pathlib import Path

import pytest

from mem0_oss_adapter_v5.domain import canonical_sha256
from mem0_oss_adapter_v5.sealed_manifest import SealedInputManifest


def _write_manifest(
    tmp_path: Path,
    contents: list[str],
    *,
    schema_version: str = "mem0-oss-adapter-v5.sealed-input.v2",
    first_unit_messages: list[dict[str, object]] | None = None,
) -> Path:
    units = []
    for sequence, content in enumerate(contents):
        messages = (
            first_unit_messages
            if sequence == 0 and first_unit_messages is not None
            else [{"role": "user", "content": content}]
        )
        unit_sha256 = canonical_sha256({"source_messages": messages})
        source_sha256 = canonical_sha256({"source": sequence})
        scope_payload = {
            "corpus_id": "corpus-r14",
            "source_id": f"source-{sequence}",
            "source_sha256": source_sha256,
            "unit_sha256": unit_sha256,
        }
        scope_sha256 = canonical_sha256(scope_payload)
        unit = {
            "sequence": sequence,
            "unit_identity_sha256": canonical_sha256(
                {
                    "sequence": sequence,
                    "scope_sha256": scope_sha256,
                    "unit_sha256": unit_sha256,
                }
            ),
            "unit_sha256": unit_sha256,
            "scope_sha256": scope_sha256,
            "corpus_id": "corpus-r14",
            "source_id": f"source-{sequence}",
            "observation_date": "2026-08-09",
            "source_messages": messages,
        }
        if schema_version.endswith(".v2"):
            unit["source_sha256"] = source_sha256
        units.append(unit)
    ingestion_root = canonical_sha256(
        {
            "units": [
                {
                    "unit_identity_sha256": unit["unit_identity_sha256"],
                    "unit_sha256": unit["unit_sha256"],
                    "scope_sha256": unit["scope_sha256"],
                }
                for unit in units
            ]
        }
    )
    unsigned = {
        "schema_version": schema_version,
        "ingestion_manifest_sha256": canonical_sha256(
            {
                "current_date": "2026-08-09",
                "ingestion_root_sha256": ingestion_root,
            }
        ),
        "ingestion_root_sha256": ingestion_root,
        "current_date": "2026-08-09",
        "units": units,
    }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    path.chmod(0o400)
    return path


@pytest.mark.parametrize("content", (" leading", "trailing ", "line\n"))
def test_v2_preserves_exact_nonempty_whitespace_and_hash(tmp_path: Path, content: str) -> None:
    manifest = SealedInputManifest(_write_manifest(tmp_path, [content]))

    assert manifest.units[0].source_messages == ({"role": "user", "content": content},)
    assert manifest.units[0].unit_sha256 == canonical_sha256(
        {"source_messages": [{"role": "user", "content": content}]}
    )


@pytest.mark.parametrize("content", ("", " ", "\t\r\n"))
def test_v2_rejects_semantically_empty_content(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match="sealed_input_invalid"):
        SealedInputManifest(_write_manifest(tmp_path, [content]))


def test_v2_rejects_content_that_is_not_utf8_encodable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sealed_input_invalid"):
        SealedInputManifest(_write_manifest(tmp_path, ["valid\ud800content"]))


@pytest.mark.parametrize(("count", "accepted"), ((100, True), (101, False)))
def test_v2_enforces_source_message_count_boundary(
    tmp_path: Path, count: int, accepted: bool
) -> None:
    messages: list[dict[str, object]] = [
        {"role": "user", "content": f"message-{index}"} for index in range(count)
    ]
    path = _write_manifest(tmp_path, ["unused"], first_unit_messages=messages)

    if accepted:
        assert len(SealedInputManifest(path).units[0].source_messages) == count
    else:
        with pytest.raises(ValueError, match="sealed_input_invalid"):
            SealedInputManifest(path)


@pytest.mark.parametrize(
    ("content", "accepted"),
    (("\u00e9" * 65_536, True), ("\u00e9" * 65_536 + "a", False)),
)
def test_v2_enforces_utf8_byte_boundary(tmp_path: Path, content: str, accepted: bool) -> None:
    path = _write_manifest(tmp_path, [content])

    if accepted:
        assert SealedInputManifest(path).units[0].source_messages[0]["content"] == content
    else:
        with pytest.raises(ValueError, match="sealed_input_invalid"):
            SealedInputManifest(path)


@pytest.mark.parametrize("role", (["user"], {"role": "user"}))
def test_v2_rejects_unhashable_role_with_stable_error(tmp_path: Path, role: object) -> None:
    messages = [{"role": role, "content": "content"}]

    with pytest.raises(ValueError, match="sealed_input_invalid"):
        SealedInputManifest(_write_manifest(tmp_path, ["unused"], first_unit_messages=messages))


def test_v1_whitespace_behavior_is_unchanged(tmp_path: Path) -> None:
    content = " \t\n"
    messages: list[dict[str, object]] = [{"role": "user", "content": content}]
    messages.extend({"role": "assistant", "content": f"legacy-{index}"} for index in range(100))
    manifest = SealedInputManifest(
        _write_manifest(
            tmp_path,
            [content],
            schema_version="mem0-oss-adapter-v5.sealed-input.v1",
            first_unit_messages=messages,
        )
    )

    assert len(manifest.units[0].source_messages) == 101
    assert manifest.units[0].source_messages[0] == {"role": "user", "content": content}


def test_r14_sized_manifest_preserves_units_78_and_311(tmp_path: Path) -> None:
    contents = [f"unit-{index}" for index in range(419)]
    contents[78] = "unit-78 "
    contents[311] = "unit-311 "

    manifest = SealedInputManifest(_write_manifest(tmp_path, contents))

    assert len(manifest.units) == 419
    assert manifest.units[78].source_messages[0]["content"].endswith(" ")
    assert manifest.units[311].source_messages[0]["content"].endswith(" ")
