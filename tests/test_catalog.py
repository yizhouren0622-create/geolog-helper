import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = catalog.Catalog(Path(self.temp.name))

    def test_coordinate_formats_and_invalid_ranges(self):
        self.assertEqual(catalog.coordinates('31.2304，121.4737'), (31.2304, 121.4737))
        lat, lng = catalog.coordinates('N31 13.824 E121 28.422')
        self.assertAlmostEqual(lat, 31.2304)
        self.assertAlmostEqual(lng, 121.4737)
        for value in ('nan,121', '91,121', '31,181', 'N31 61 E121 1', '31'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.coordinates(value)

    def test_withheld_coordinates_are_never_guessed(self):
        row = catalog.normalize({'code': 'GC12345', 'name': 'Private coordinate example', 'premiumOnly': True})
        self.assertIsNone(row['lat'])
        self.assertIsNone(row['lng'])
        row = catalog.normalize({'code': 'GC12345', 'postedCoordinates': {'latitude': None, 'longitude': None}})
        self.assertIsNone(row['lat'])

    def test_name_and_map_bounds_search_escape_wildcards(self):
        self.store.upsert([catalog.normalize({'gc': 'GC123', 'name': '100% Park', 'lat': 31.2, 'lng': 121.4}),
                           catalog.normalize({'gc': 'GC456', 'name': 'Other', 'lat': 22.2, 'lng': 114.1})])
        self.assertEqual(self.store.search('%')['total'], 1)
        self.assertEqual(self.store.search(box=[32, 120, 30, 122])['caches'][0]['gc'], 'GC123')
        self.assertEqual(self.store.search("%' OR 1=1 --")['total'], 0)

    def test_failed_region_refresh_preserves_old_data_and_success_date(self):
        old = time.time() - 100
        self.store.set_meta('region:shanghai', {'last_update': old, 'next_update': 0})
        self.store.upsert([catalog.normalize({'gc': 'GC123', 'name': 'Old'})])
        def fail(*_):
            raise OSError('offline')
        self.store.sync_regions(fail, True)
        self.assertEqual(self.store.meta('region:shanghai')['last_update'], old)
        self.assertEqual(self.store.meta('region:shanghai')['state'], 'error')
        self.assertEqual(self.store.search()['total'], 1)

    def test_refresh_dates_and_pagination(self):
        def fetch(item, skip):
            return {'caches': [catalog.normalize({'gc': 'GC' + str(100 + skip), 'name': item['region']})], 'total': 1}
        self.store.sync_regions(fetch)
        self.assertEqual(self.store.due_regions(), [])
        self.assertAlmostEqual(self.store.meta('region:shanghai')['next_update'] - self.store.meta('region:shanghai')['last_update'], 15 * 86400)

    def test_invalid_map_and_missing_global_source(self):
        with self.assertRaises(ValueError):
            catalog.query_params({'box': [90, -180, -90, 180]})
        self.assertEqual(self.store.sync_global()['state'], 'unconfigured')
        self.assertFalse(self.store.status()['global_configured'])

    def test_rate_limit_keeps_pages_and_resumes_after_backoff(self):
        class Limited(Exception): retry_after = 3600
        def first(item, skip):
            if skip:
                raise Limited('rate limited')
            return {'caches': [catalog.normalize({'gc': 'GC' + str(i), 'name': 'Page 1'}) for i in range(100)], 'total': 200}
        with patch.object(catalog.time, 'sleep'):
            self.store.sync_regions(first)
        self.assertEqual(self.store.search()['total'], 100)
        self.assertEqual(self.store.meta('region:shanghai')['resume_skip'], 100)
        self.assertEqual(self.store.due_regions(), [])
        self.store.set_meta('backoff_until', 0)
        def second(item, skip):
            if item['region'] == 'shanghai':
                self.assertEqual(skip, 100)
                return {'caches': [catalog.normalize({'gc': 'GC' + str(i), 'name': 'Page 2'}) for i in range(100, 200)], 'total': 200}
            return {'caches': [], 'total': 0}
        with patch.object(catalog.time, 'sleep'):
            self.store.sync_regions(second)
        self.assertEqual(self.store.meta('region:shanghai')['loaded'], 200)
        self.assertEqual(self.store.meta('region:shanghai')['state'], 'ok')

    def test_global_csv_import_is_atomic_and_six_calendar_months(self):
        class Response(io.BytesIO):
            headers = {}
        class Opener:
            def __init__(self, data): self.data = data
            def open(self, *args, **kwargs): return Response(self.data)
        self.store.set_meta('global_url', 'https://example.org/caches.csv')
        with patch.object(catalog, 'public_feed_url', side_effect=lambda value: value):
            good = self.store.sync_global(opener=Opener(b'gc,name,lat,lng\nGC123,First,31,121\n'))
            self.assertEqual(good['state'], 'ok')
            self.assertEqual(good['next_update'], catalog.six_months_later(good['last_update']))
            bad = self.store.sync_global(True, Opener(b'gc,name,lat,lng\nGC456,Second,31,121\nINVALID,Oops,31,121\n'))
            self.assertEqual(bad['state'], 'error')
            self.assertEqual(self.store.search()['total'], 1)
            self.assertEqual(self.store.search()['caches'][0]['gc'], 'GC123')


if __name__ == '__main__': unittest.main()
