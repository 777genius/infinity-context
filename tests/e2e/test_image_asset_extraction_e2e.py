import json
import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from memo_stack_server_harness import run_memo_stack_server
from PIL import Image, ImageDraw, ImageFont


def test_image_asset_extraction_persists_region_artifact_e2e(tmp_path: Path) -> None:
    with (
        run_memo_stack_server(
            tmp_path,
            database_name="image-asset-extraction.db",
            extra_env={"MEMORY_ASSET_STORAGE_DIR": str(tmp_path / "assets")},
        ) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "image-extraction-e2e",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "capture.png",
                "extract": "true",
            },
            content=_sample_png_bytes(),
            headers={"Content-Type": "image/png"},
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "memo_stack_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            env=server.env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert worker.returncode == 0, worker.stdout + worker.stderr

        extracted = client.get(f"/v1/asset-extractions/{extraction_id}")
        assert extracted.status_code == 200, extracted.text
        extraction = extracted.json()["data"]
        assert extraction["status"] == "succeeded"
        assert extraction["parser_name"] == "image_metadata"
        assert extraction["metadata"]["image_width"] == 120
        assert extraction["metadata"]["image_height"] == 40

        artifact_types = {item["artifact_type"] for item in extraction["artifacts"]}
        assert artifact_types == {
            "extracted_json",
            "image_regions",
            "markdown",
            "media_manifest",
        }
        regions = next(
            item for item in extraction["artifacts"] if item["artifact_type"] == "image_regions"
        )
        download = client.get(f"/v1/extraction-artifacts/{regions['id']}/download")
        assert download.status_code == 200, download.text
        payload = json.loads(download.content.decode("utf-8"))
        assert payload["schema_name"] == "memo_stack.image_regions"
        assert payload["image"]["image_width"] == 120
        assert payload["regions"][0]["bbox"] == [0.0, 0.0, 120.0, 40.0]

        manifest = next(
            item for item in extraction["artifacts"] if item["artifact_type"] == "media_manifest"
        )
        manifest_download = client.get(f"/v1/extraction-artifacts/{manifest['id']}/download")
        assert manifest_download.status_code == 200, manifest_download.text
        manifest_payload = manifest_download.json()
        assert manifest_payload["schema_version"] == "memo_stack.multimodal_manifest.v1"
        assert manifest_payload["features"]["modalities"] == ["text", "image"]
        assert manifest_payload["features"]["coordinate_fields_present"] == ["bbox"]
        assert manifest_payload["features"]["has_bbox_refs"] is True


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not installed")
def test_image_asset_extraction_persists_ocr_regions_e2e(tmp_path: Path) -> None:
    with (
        run_memo_stack_server(
            tmp_path,
            database_name="image-ocr-extraction.db",
            extra_env={"MEMORY_ASSET_STORAGE_DIR": str(tmp_path / "assets")},
        ) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "image-ocr-e2e",
                "memory_scope_external_ref": "frontend",
                "thread_external_ref": "screenshots",
                "filename": "ocr-capture.png",
                "extract": "true",
            },
            content=_sample_text_png_bytes(),
            headers={"Content-Type": "image/png"},
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "memo_stack_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            env=server.env,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        assert worker.returncode == 0, worker.stdout + worker.stderr

        extracted = client.get(f"/v1/asset-extractions/{extraction_id}")
        assert extracted.status_code == 200, extracted.text
        extraction = extracted.json()["data"]
        assert extraction["status"] == "succeeded"
        assert extraction["metadata"]["ocr_status"] == "extracted"
        assert extraction["metadata"]["ocr_block_count"] >= 1

        regions = next(
            item for item in extraction["artifacts"] if item["artifact_type"] == "image_regions"
        )
        download = client.get(f"/v1/extraction-artifacts/{regions['id']}/download")
        assert download.status_code == 200, download.text
        payload = json.loads(download.content.decode("utf-8"))
        ocr_regions = [item for item in payload["regions"] if item["kind"] == "ocr_text"]
        assert ocr_regions
        assert "MEMORY" in " ".join(item["text"] for item in ocr_regions)


def _sample_png_bytes() -> bytes:
    image = Image.new("RGB", (120, 40), color=(255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _sample_text_png_bytes() -> bytes:
    image = Image.new("RGB", (420, 150), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.text((24, 36), "MEMORY SCOPE", fill=(0, 0, 0), font=ImageFont.load_default(size=42))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
