"""Strict V3 wire isolation against immutable V2 synthetic request fixtures."""
import copy
import json
from pathlib import Path
import unittest

from infinity_context_contracts.features.context_building import RetrieveContextRequestDto
from infinity_context_contracts.features.context_retrieval_v3 import (
    RetrieveContextV3RequestDto, decode_retrieve_context_v3_request,
    RetrieveContextV3ResponseDto, retrieval_v3_capability, validate_retrieval_v3_capability,
)

from infinity_context_contracts.features.context_building import (
    RetrievalCapabilityDto, RetrieveContextResponseDto,
)

FIXTURE = Path(__file__).resolve().parents[2] / (
    "packages/infinity_context_contracts/infinity_context_contracts/fixtures/"
    "context_retrieval_v2/request.json"
)


class ThreadSelectorWireTests(unittest.TestCase):
    def setUp(self):
        self.v2 = json.loads(FIXTURE.read_text())
        self.v3 = copy.deepcopy(self.v2)
        self.v3["contract_version"] = "context-retrieval.v3"
        scope = self.v2["scope"]
        self.v3["scope"] = {
            "spaceId": scope["space_id"], "memoryScopeId": scope["memory_scope_id"],
            "thread": {"mode": "any"},
        }

    def test_roundtrip_and_v2_stays_strict(self):
        self.assertEqual(RetrieveContextRequestDto.from_dict(self.v2).to_dict(), self.v2)
        for selector in ({"mode": "any"}, {"mode": "exact", "id": None},
                         {"mode": "exact", "id": "meeting-a"}):
            self.v3["scope"]["thread"] = selector
            self.assertEqual(
                decode_retrieve_context_v3_request(json.dumps(self.v3).encode()).to_dict(), self.v3
            )
            with self.assertRaises(ValueError):
                RetrieveContextRequestDto.from_dict(self.v3)
        with self.assertRaises(ValueError):
            RetrieveContextV3RequestDto.from_dict(self.v2)

    def test_separate_capability_and_response_versions(self):
        old = json.loads(FIXTURE.with_name("capability.json").read_text())
        descriptor = RetrievalCapabilityDto.from_dict(old)
        new = retrieval_v3_capability(descriptor)
        self.assertNotEqual(new["capability_fingerprint"], old["capability_fingerprint"])
        self.assertEqual(validate_retrieval_v3_capability(new), new)
        with self.assertRaises(ValueError):
            RetrievalCapabilityDto.from_dict(new)
        with self.assertRaises(ValueError):
            validate_retrieval_v3_capability(old)
        forged = {**new, "profile_id": "other"}
        with self.assertRaises(ValueError):
            validate_retrieval_v3_capability(forged)
        response = json.loads(FIXTURE.with_name("success.json").read_text())
        self.assertEqual(RetrieveContextResponseDto.from_dict(response).to_dict(), response)
        response["contract_version"] = "context-retrieval.v3"
        self.assertEqual(RetrieveContextV3ResponseDto.from_dict(response).to_dict(), response)
        with self.assertRaises(ValueError):
            RetrieveContextResponseDto.from_dict(response)

    def test_invalid_selectors(self):
        for selector in ({"mode": "exact"}, {"mode": "any", "id": None},
                         {"mode": "unknown"}, {"mode": "exact", "id": 1},
                         {"mode": "exact", "id": ""}, {"mode": "any", "extra": True},
                         None, "any", {"mode": []}):
            with self.subTest(selector=selector):
                self.v3["scope"]["thread"] = selector
                with self.assertRaises(ValueError):
                    RetrieveContextV3RequestDto.from_dict(self.v3)

    def test_conflicting_scalar_and_duplicate_keys(self):
        self.v3["scope"]["threadId"] = None
        with self.assertRaises(ValueError):
            RetrieveContextV3RequestDto.from_dict(self.v3)
        del self.v3["scope"]["threadId"]
        raw = json.dumps(self.v3).replace('"mode": "any"', '"mode": "exact", "mode": "any"')
        with self.assertRaises(ValueError):
            decode_retrieve_context_v3_request(raw.encode())


if __name__ == "__main__":
    unittest.main()
