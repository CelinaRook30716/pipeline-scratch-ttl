import unittest

from expire_devtools import created_at_from_key, expire_objects
from infrai_client import _BucketAPI


class FakeObjects:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.deleted: list[str] = []

    def list(self, bucket: str) -> dict[str, object]:
        return {"items": [{"key": key} for key in self.keys]}

    def delete(self, bucket: str, key: str) -> dict[str, object]:
        self.deleted.append(key)
        return {"key": key}


class ExpireObjectsTest(unittest.TestCase):
    def test_bucket_create_sends_required_name(self) -> None:
        calls: list[tuple[str, str, dict[str, str]]] = []

        def call(method: str, path: str, body: dict[str, str]) -> dict[str, object]:
            calls.append((method, path, body))
            return {}

        _BucketAPI(call).create("pipeline-devtools")

        self.assertEqual(
            calls,
            [
                (
                    "POST",
                    "/v1/storage/bucket/create",
                    {
                        "name": "pipeline-devtools",
                        "bucket": "pipeline-devtools",
                        "idempotency_key": "create-bucket:pipeline-devtools",
                    },
                )
            ],
        )

    def test_deletes_only_expired_keys_in_the_pipeline_prefix(self) -> None:
        objects = FakeObjects(
            [
                "scratch/100-build-log.json",
                "scratch/950-query-plan.json",
                "releases/100-artifact.zip",
                "scratch/missing-epoch.json",
            ]
        )

        report = expire_objects(
            objects,
            "pipeline-devtools",
            prefix="scratch/",
            ttl_seconds=100,
            now=1000,
        )

        self.assertEqual(report.scanned, 4)
        self.assertEqual(report.deleted, ("scratch/100-build-log.json",))
        self.assertEqual(objects.deleted, ["scratch/100-build-log.json"])

    def test_dry_run_reports_without_deleting(self) -> None:
        objects = FakeObjects(["scratch/100-profile.json"])

        report = expire_objects(
            objects,
            "pipeline-devtools",
            prefix="scratch/",
            ttl_seconds=100,
            now=1000,
            dry_run=True,
        )

        self.assertEqual(report.deleted, ("scratch/100-profile.json",))
        self.assertEqual(objects.deleted, [])

    def test_key_parser_rejects_other_naming_schemes(self) -> None:
        self.assertEqual(created_at_from_key("scratch/123-run.json", "scratch/"), 123)
        self.assertIsNone(created_at_from_key("scratch/run.json", "scratch/"))
        self.assertIsNone(created_at_from_key("archive/123-run.json", "scratch/"))


if __name__ == "__main__":
    unittest.main()
