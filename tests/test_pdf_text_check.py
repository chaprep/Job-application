"""PDF text fidelity tolerates typography, but still rejects missing content."""
import csv
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from backend.errors import BackendError
from backend.rendering import pdf_check


class PDFTextChecks(unittest.TestCase):
    def check(self, actual, expected, x=20):
        output = StringIO()
        writer = csv.writer(output, delimiter='\t', quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(['level', 'left', 'top', 'width', 'height', 'text'])
        writer.writerow([1, 0, 0, 595.28, 841.89, ''])
        for word in actual.split():
            writer.writerow([5, x, 20, 300, 12, word])
        result = CompletedProcess([], 0, stdout=output.getvalue())
        with patch('backend.rendering.subprocess.run', return_value=result):
            return pdf_check(Path('fixture.pdf'), [expected])

    def test_quote_styles_and_layout_whitespace_are_equivalent(self):
        for actual, expected in [
            ("an AE’s calendar", "an AE's calendar"),
            ('He said “hello”.', 'He said "hello".'),
            ("‘hello’", "'hello'"),
            ('"hello"', '“hello”'),
            ("AE’s\u00a0calendar\nfor\tmeetings", "AE's calendar for meetings"),
        ]:
            with self.subTest(actual=actual, expected=expected):
                self.assertTrue(self.check(actual, expected)['text_verified'])

    def test_missing_or_changed_content_still_fails(self):
        for actual, expected in [
            ('an AE’s', "an AE's calendar"),
            ('Reduced costs by 80%.', 'Reduced costs by 90%.'),
            ('We can do it.', "We can't do it."),
        ]:
            with self.subTest(actual=actual):
                with self.assertRaises(BackendError) as error:
                    self.check(actual, expected)
                self.assertEqual(error.exception.code, 'pdf_missing_text')

    def test_clipping_and_invalid_character_checks_remain(self):
        with self.assertRaises(BackendError) as error:
            self.check('hello', 'hello', x=0)
        self.assertEqual(error.exception.code, 'pdf_clipping')
        with self.assertRaises(BackendError) as error:
            self.check('hello\ufffd', 'hello')
        self.assertEqual(error.exception.code, 'pdf_text_mapping')
