"""Tests for the OBS sink.

The row builders are pure Python (no deps). The Parquet-encoding and upload tests
need ``pyarrow`` and are skipped if it isn't installed; the OBS SDK is never
needed — a fake client captures the uploaded objects.
"""

import io
import json
import sys
import types
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from special_days.models import SpecialDate
from special_days.sinks import obs

try:
    import pyarrow  # noqa: F401
    import pyarrow.parquet  # noqa: F401
    _HAS_PYARROW = True
except Exception:  # pragma: no cover - import guard
    _HAS_PYARROW = False

TS = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _rec(**kw) -> SpecialDate:
    base = dict(
        event="X",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        city="Istanbul",
        category="public_holiday",
        country="TR",
        source="nager",
    )
    base.update(kw)
    return SpecialDate(**base)


def _features_by_cell(rows):
    out = {}
    for row in rows:
        d = dict(zip(obs.FEATURE_COLUMNS, row))
        out[(d["event_date"], d["country"], d["airport"])] = d
    return out


class RecordKeyTest(unittest.TestCase):
    def test_deterministic_for_same_identity(self):
        self.assertEqual(obs.record_key(_rec()), obs.record_key(_rec()))

    def test_excludes_enrichment_fields(self):
        bare = _rec()
        enriched = _rec(
            impact_score=90, nearest_airport="IST", airport_distance_km=3.2,
            predicted_attendance=1000, impact_by_day=(("2026-01-01", 90),),
        )
        self.assertEqual(obs.record_key(bare), obs.record_key(enriched))

    def test_distinguishes_source_and_coords(self):
        self.assertNotEqual(obs.record_key(_rec(source="nager")), obs.record_key(_rec(source="diyanet")))
        self.assertNotEqual(
            obs.record_key(_rec(lat=41.0, lon=29.0)),
            obs.record_key(_rec(lat=39.9, lon=32.8)),
        )


class RawRowsTest(unittest.TestCase):
    def test_one_tuple_per_record_aligned_to_columns(self):
        rows = obs.to_raw_rows([_rec(event="A"), _rec(event="B")], "run", TS)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), len(obs.RAW_COLUMNS))

    def test_dedup_by_key_last_wins(self):
        rows = obs.to_raw_rows([_rec(impact_score=10), _rec(impact_score=90)], "run", TS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(dict(zip(obs.RAW_COLUMNS, rows[0]))["impact_score"], 90)

    def test_dates_passed_through_and_curves_jsonified(self):
        rec = _rec(
            start_date=date(2026, 5, 1), end_date=date(2026, 5, 2),
            impact_by_day=(("2026-05-01", 70), ("2026-05-02", 50)), impact_by_day_bridge=None,
        )
        d = dict(zip(obs.RAW_COLUMNS, obs.to_raw_rows([rec], "run", TS)[0]))
        self.assertEqual(d["start_date"], date(2026, 5, 1))
        self.assertEqual(json.loads(d["impact_by_day"]), {"2026-05-01": 70, "2026-05-02": 50})
        self.assertIsNone(d["impact_by_day_bridge"])
        self.assertEqual(d["load_ts"], TS)


class ExplodeFeaturesTest(unittest.TestCase):
    def test_event_explodes_to_one_row_per_day_at_airport(self):
        ev = _rec(
            event="Concert", category="concert", source="ticketmaster",
            lat=41.0, lon=29.0, nearest_airport="IST",
            start_date=date(2026, 5, 1), end_date=date(2026, 5, 3),
            impact_score=40, predicted_attendance=1000,
            impact_by_day=(("2026-05-01", 40), ("2026-05-02", 20), ("2026-05-03", 40)),
            impact_by_day_bridge=(("2026-05-01", 40), ("2026-05-02", 20), ("2026-05-03", 40)),
        )
        cells = _features_by_cell(obs.explode_features([ev], "run", TS))
        self.assertEqual(len(cells), 3)
        mid = cells[(date(2026, 5, 2), "TR", "IST")]
        self.assertEqual(mid["impact"], 20)
        self.assertEqual(mid["predicted_attendance"], 1000)
        self.assertEqual(mid["n_events"], 1)

    def test_national_holiday_kept_with_null_airport(self):
        hol = _rec(
            event="Bayram", category="religious_holiday", source="diyanet", nearest_airport=None,
            start_date=date(2026, 5, 2), end_date=date(2026, 5, 2), impact_score=99,
            impact_by_day=(("2026-05-02", 99),), impact_by_day_bridge=(("2026-05-02", 99),),
        )
        cells = _features_by_cell(obs.explode_features([hol], "run", TS))
        self.assertIn((date(2026, 5, 2), "TR", None), cells)
        self.assertIsNone(cells[(date(2026, 5, 2), "TR", None)]["predicted_attendance"])

    def test_bridge_curve_merged_by_per_day_max(self):
        hol = _rec(
            event="Bayram", category="religious_holiday", source="diyanet", nearest_airport=None,
            start_date=date(2026, 5, 2), end_date=date(2026, 5, 2), impact_score=99,
            impact_by_day=(("2026-05-02", 99),),
            impact_by_day_bridge=(("2026-05-01", 70), ("2026-05-02", 80), ("2026-05-03", 70)),
        )
        cells = _features_by_cell(obs.explode_features([hol], "run", TS))
        self.assertEqual(cells[(date(2026, 5, 1), "TR", None)]["impact"], 70)
        self.assertEqual(cells[(date(2026, 5, 2), "TR", None)]["impact"], 99)
        self.assertEqual(cells[(date(2026, 5, 3), "TR", None)]["impact"], 70)

    def test_same_cell_aggregates_across_events(self):
        day = date(2026, 5, 2)
        a = _rec(
            event="Concert A", category="concert", source="ticketmaster", nearest_airport="IST",
            lat=41.0, lon=29.0, start_date=day, end_date=day, impact_score=40, predicted_attendance=1000,
            impact_by_day=(("2026-05-02", 40),), impact_by_day_bridge=(("2026-05-02", 40),),
        )
        b = _rec(
            event="Match B", category="sports", source="football", nearest_airport="IST",
            lat=41.0, lon=29.1, start_date=day, end_date=day, impact_score=55, predicted_attendance=500,
            impact_by_day=(("2026-05-02", 55),), impact_by_day_bridge=(("2026-05-02", 55),),
        )
        cell = _features_by_cell(obs.explode_features([a, b], "run", TS))[(day, "TR", "IST")]
        self.assertEqual(cell["impact"], 55)
        self.assertEqual(cell["predicted_attendance"], 1500)
        self.assertEqual(cell["n_events"], 2)
        self.assertEqual(cell["sources"], "football,ticketmaster")

    def test_fallback_curve_when_unenriched(self):
        rec = _rec(
            start_date=date(2026, 5, 1), end_date=date(2026, 5, 2), impact_score=33,
            nearest_airport=None, impact_by_day=None, impact_by_day_bridge=None,
        )
        cells = _features_by_cell(obs.explode_features([rec], "run", TS))
        self.assertEqual(len(cells), 2)
        self.assertEqual(cells[(date(2026, 5, 1), "TR", None)]["impact"], 33)


class ObsUriTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(obs.parse_obs_uri("obs://lakehouse-dev/special_events"), ("lakehouse-dev", "special_events"))
        self.assertEqual(obs.parse_obs_uri("obs://bucket/a/b/c"), ("bucket", "a/b/c"))
        self.assertEqual(obs.parse_obs_uri("obs://bucket"), ("bucket", ""))
        self.assertEqual(obs.parse_obs_uri("bucket/prefix"), ("bucket", "prefix"))

    def test_object_key_skips_empty_prefix(self):
        self.assertEqual(obs._object_key("", "special_days_raw", "data.parquet"), "special_days_raw/data.parquet")
        self.assertEqual(
            obs._object_key("special_events", "special_days_raw", "data.parquet"),
            "special_events/special_days_raw/data.parquet",
        )


class SchemaAlignmentTest(unittest.TestCase):
    def test_column_counts(self):
        self.assertEqual(len(obs.RAW_COLUMNS), 20)
        self.assertEqual(len(obs.FEATURE_COLUMNS), 9)


class _FakeResp:
    status = 200
    errorCode = None
    errorMessage = None


class _ErrorResp:
    def __init__(self, status, error_code, error_message):
        self.status = status
        self.errorCode = error_code
        self.errorMessage = error_message


class _FakeObsClient:
    def __init__(self):
        self.puts = {}
        self.closed = False

    def put_object(self, Bucket=None, Key=None, Body=None):
        self.puts[(Bucket, Key)] = Body

    def putContent(self, bucket, key, content=None):
        self.puts[(bucket, key)] = content
        return _FakeResp()

    def close(self):
        self.closed = True


class PutErrorTest(unittest.TestCase):
    def test_signature_mismatch_error_includes_hint(self):
        client = unittest.mock.Mock()
        client.putContent.return_value = _ErrorResp(403, "SignatureDoesNotMatch", "bad signature")

        with self.assertRaises(RuntimeError) as exc:
            obs._put(client, "lakehouse-dev", "special_events/data.parquet", b"x")

        message = str(exc.exception)
        self.assertIn("SignatureDoesNotMatch", message)
        self.assertIn("OBS_ACCESS_KEY / OBS_SECRET_KEY", message)

    def test_thy_s3_service_failure_is_wrapped(self):
        service = mock.Mock()
        service.save_memory_file_to_s3.side_effect = RuntimeError("access denied")
        client = obs._ThyS3CompatClient(service, "lakehouse-dev")

        with self.assertRaises(RuntimeError) as exc:
            obs._put(client, "lakehouse-dev", "special_events/data.parquet", b"x")

        service.save_memory_file_to_s3.assert_called_once_with(b"x", "special_events/data.parquet")
        message = str(exc.exception)
        self.assertIn("Object-store upload failed", message)
        self.assertIn("access denied", message)


class ObsClientConfigTest(unittest.TestCase):
    def test_thy_internal_endpoint_uses_thy_s3_service(self):
        service = mock.Mock()
        ctor = mock.Mock(return_value=service)
        fake_thy_pkg = types.ModuleType("thy")
        fake_thy_s3 = types.ModuleType("thy.s3")
        fake_thy_s3.ThyS3Service = ctor
        fake_thy_pkg.s3 = fake_thy_s3
        with mock.patch.dict(sys.modules, {"thy": fake_thy_pkg, "thy.s3": fake_thy_s3}):
            out = obs._obs_client("bigdata-dev.obs.thy.com", "ak", "sk", bucket_name="lakehouse-dev")
        self.assertIsInstance(out, obs._ThyS3CompatClient)
        ctor.assert_called_once_with(
            access_key="ak",
            secret_key="sk",
            bucket_name="lakehouse-dev",
            endpoint_url="https://bigdata-dev.obs.thy.com",
        )
        out.putContent("lakehouse-dev", "special_events/data.parquet", b"x")
        service.save_memory_file_to_s3.assert_called_once_with(
            b"x",
            "special_events/data.parquet",
        )

    def test_official_obs_endpoint_keeps_virtual_host_style(self):
        ctor = mock.Mock(return_value="client")
        with mock.patch.dict(sys.modules, {"obs": types.SimpleNamespace(ObsClient=ctor)}):
            obs._obs_client("https://obs.cn-north-4.myhuaweicloud.com", "ak", "sk", bucket_name="bucket")
        ctor.assert_called_once_with(
            access_key_id="ak",
            secret_access_key="sk",
            server="https://obs.cn-north-4.myhuaweicloud.com",
        )

    def test_non_thy_non_official_endpoint_falls_back_to_boto3(self):
        ctor = mock.Mock(return_value=mock.Mock())
        with mock.patch.dict(sys.modules, {"boto3": types.SimpleNamespace(client=ctor)}):
            out = obs._obs_client("files.example.com", "ak", "sk", bucket_name="bucket")
        self.assertIsInstance(out, obs._S3CompatClient)
        ctor.assert_called_once_with(
            "s3",
            endpoint_url="https://files.example.com",
            aws_access_key_id="ak",
            aws_secret_access_key="sk",
            verify=False,
        )


@unittest.skipUnless(_HAS_PYARROW, "pyarrow not installed")
class ParquetWriteTest(unittest.TestCase):
    def _records(self):
        hol = _rec(
            event="Bayram", category="religious_holiday", source="diyanet", nearest_airport=None,
            start_date=date(2026, 5, 2), end_date=date(2026, 5, 2), impact_score=99,
            impact_by_day=(("2026-05-02", 99),),
            impact_by_day_bridge=(("2026-05-01", 70), ("2026-05-02", 99), ("2026-05-03", 70)),
        )
        ev = _rec(
            event="Concert", category="concert", source="ticketmaster", nearest_airport="IST",
            lat=41.0, lon=29.0, start_date=date(2026, 5, 2), end_date=date(2026, 5, 3),
            impact_score=40, predicted_attendance=1000,
            impact_by_day=(("2026-05-02", 40), ("2026-05-03", 40)),
            impact_by_day_bridge=(("2026-05-02", 40), ("2026-05-03", 40)),
        )
        return [hol, ev]

    def _read(self, content):
        import pyarrow.parquet as pq
        return pq.read_table(io.BytesIO(content))

    def test_write_uploads_two_objects_at_expected_keys(self):
        client = _FakeObsClient()
        run_id = obs.write(
            self._records(), endpoint="bigdata-dev.obs", access_key="a", secret_key="s",
            location="obs://lakehouse-dev/special_events", client=client,
        )
        self.assertTrue(run_id)
        self.assertEqual(
            set(client.puts),
            {
                ("lakehouse-dev", "special_events/special_days_raw/data.parquet"),
                ("lakehouse-dev", "special_events/special_days_features/data.parquet"),
            },
        )
        self.assertFalse(client.closed)  # injected client is not closed by the sink

    def test_written_parquet_is_valid_and_matches_schema(self):
        client = _FakeObsClient()
        obs.write(
            self._records(), endpoint="e", access_key="a", secret_key="s",
            location="obs://lakehouse-dev/special_events", client=client,
        )
        raw = self._read(client.puts[("lakehouse-dev", "special_events/special_days_raw/data.parquet")])
        feat = self._read(client.puts[("lakehouse-dev", "special_events/special_days_features/data.parquet")])
        self.assertEqual(raw.column_names, list(obs.RAW_COLUMNS))
        self.assertEqual(raw.num_rows, 2)                       # two distinct records
        self.assertEqual(feat.column_names, list(obs.FEATURE_COLUMNS))
        self.assertEqual(feat.num_rows, 5)                      # 3 national days + 2 IST days
        airports = feat.column("airport").to_pylist()
        self.assertEqual(airports.count(None), 3)              # national holiday rows kept as NULL

    def test_empty_records_still_writes_valid_empty_parquet(self):
        client = _FakeObsClient()
        obs.write(
            [], endpoint="e", access_key="a", secret_key="s",
            location="obs://lakehouse-dev/special_events", client=client,
        )
        feat = self._read(client.puts[("lakehouse-dev", "special_events/special_days_features/data.parquet")])
        self.assertEqual(feat.num_rows, 0)
        self.assertEqual(feat.column_names, list(obs.FEATURE_COLUMNS))


if __name__ == "__main__":
    unittest.main()
