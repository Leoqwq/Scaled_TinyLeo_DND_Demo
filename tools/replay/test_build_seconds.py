import json
import re
import unittest

from build_seconds import render_html


class BundledComparisonTests(unittest.TestCase):
    def test_optional_recordings_are_embedded_as_safe_json(self):
        pair={'shortest': {'source':'</script><script>bad()'}, 'qos':{'source':'q'}}
        page=render_html({'modes':{}}, comparison=pair)
        raw=re.search(r'<script id="comparisonData" type="application/json">(.*?)</script>',page,re.S)[1]
        self.assertEqual(json.loads(raw),pair)
        self.assertNotIn('</script>',raw)

    def test_legacy_build_has_no_bundled_pair(self):
        page=render_html({'modes':{}})
        self.assertIn('<script id="comparisonData" type="application/json">null</script>',page)
