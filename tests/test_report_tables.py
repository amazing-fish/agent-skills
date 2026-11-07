"""Offline integration plus executable table logic; not a visual test."""
from pathlib import Path
import importlib.util
import re
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'skills/report-for-human'
spec=importlib.util.spec_from_file_location('table_report_controls',SKILL/'scripts/add_report_controls.py')
controls=importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
class Tables(unittest.TestCase):
    def test_enhancement_inlines_table_assets_and_is_idempotent(self):
        source=(SKILL/'examples/tables.html').read_text()
        result=controls.enhance_report(source)
        for name in ('report-tables.css','report-tables.js'):
            self.assertIn((SKILL/'assets'/name).read_text(),result)
        twice=controls.enhance_report(result)
        self.assertEqual(twice.count(controls.HEAD_START),1)
        self.assertEqual(twice.count('<table '),source.count('<table '))
        self.assertNotRegex(result,r'<(?:script|img)[^>]+src=|<link[^>]+href=')
        self.assertIn('<col style="width:22%">',twice)
    def test_no_universal_compression_and_print_ignores_user_pixels(self):
        css=(SKILL/'assets/report-theme.css').read_text()
        self.assertNotRegex(css,r'width:\s*1%')
        styles=(SKILL/'assets/report-tables.css').read_text()
        printing=styles.split('@media print',1)[1]
        self.assertIn('table-layout:auto!important',printing)
        self.assertIn('width:auto!important',printing)
        self.assertIn('display:none!important',printing)
    @unittest.skipUnless(shutil.which('node'),'Node required for mocked DOM checks')
    def test_executable_table_behavior(self):
        subprocess.run(['node',str(ROOT/'tests/report_tables_behavior.cjs')],check=True,capture_output=True,text=True)
if __name__=='__main__': unittest.main()
