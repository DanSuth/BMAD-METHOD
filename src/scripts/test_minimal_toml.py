"""Tests for _minimal_toml.

Run:  python3 src/scripts/test_minimal_toml.py
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _minimal_toml as mt  # noqa: E402


class TestBasicScalars(unittest.TestCase):
    def test_empty_file(self):
        self.assertEqual(mt.loads(""), {})

    def test_comments_only(self):
        src = "# a comment\n   # another\n\n# trailing"
        self.assertEqual(mt.loads(src), {})

    def test_basic_string(self):
        self.assertEqual(mt.loads('x = "hello"'), {"x": "hello"})

    def test_string_with_escapes(self):
        self.assertEqual(
            mt.loads(r'x = "a\tb\nc\"d\\e"'),
            {"x": "a\tb\nc\"d\\e"},
        )

    def test_unicode_escape(self):
        self.assertEqual(mt.loads(r'x = "é"'), {"x": "é"})

    def test_unicode_literal(self):
        self.assertEqual(mt.loads('x = "🔒"'), {"x": "🔒"})

    def test_booleans(self):
        self.assertEqual(mt.loads("a = true\nb = false\n"), {"a": True, "b": False})

    def test_true_is_not_a_prefix(self):
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads("x = truee")

    def test_inline_comment_after_value(self):
        self.assertEqual(mt.loads('x = "v"  # comment\n'), {"x": "v"})


class TestMultilineStrings(unittest.TestCase):
    def test_basic_multiline(self):
        src = 'x = """hello"""'
        self.assertEqual(mt.loads(src), {"x": "hello"})

    def test_multiline_trims_leading_newline(self):
        src = 'x = """\nhello\nworld"""'
        self.assertEqual(mt.loads(src), {"x": "hello\nworld"})

    def test_multiline_with_internal_quotes(self):
        src = 'x = """she said "hi" then left"""'
        self.assertEqual(mt.loads(src), {"x": 'she said "hi" then left'})

    def test_multiline_spans_many_lines(self):
        src = 'x = """\nl1\nl2\nl3\nl4\nl5"""'
        self.assertEqual(mt.loads(src), {"x": "l1\nl2\nl3\nl4\nl5"})

    def test_multiline_trailing_quotes(self):
        # Five quotes at the end: """ closes, and the leading two count as content.
        src = 'x = """ends with quote: """""'
        self.assertEqual(mt.loads(src), {"x": 'ends with quote: ""'})

    def test_line_ending_backslash(self):
        src = 'x = """one \\\n   two"""'
        self.assertEqual(mt.loads(src), {"x": "one two"})


class TestArrays(unittest.TestCase):
    def test_inline_string_array(self):
        self.assertEqual(mt.loads('x = ["a", "b", "c"]'), {"x": ["a", "b", "c"]})

    def test_empty_array(self):
        self.assertEqual(mt.loads("x = []"), {"x": []})

    def test_multiline_array(self):
        src = 'x = [\n  "a",\n  "b",\n  "c",\n]\n'
        self.assertEqual(mt.loads(src), {"x": ["a", "b", "c"]})

    def test_array_with_comments(self):
        src = 'x = [\n  "a",  # first\n  # skip\n  "b",\n]\n'
        self.assertEqual(mt.loads(src), {"x": ["a", "b"]})

    def test_bool_array(self):
        self.assertEqual(mt.loads("x = [true, false, true]"), {"x": [True, False, True]})


class TestTables(unittest.TestCase):
    def test_simple_table(self):
        src = "[a]\nx = \"1\"\ny = \"2\"\n"
        self.assertEqual(mt.loads(src), {"a": {"x": "1", "y": "2"}})

    def test_dotted_table(self):
        src = "[a.b]\nx = \"1\"\n"
        self.assertEqual(mt.loads(src), {"a": {"b": {"x": "1"}}})

    def test_array_of_tables(self):
        src = '[[items]]\ncode = "a"\n\n[[items]]\ncode = "b"\n'
        self.assertEqual(mt.loads(src), {"items": [{"code": "a"}, {"code": "b"}]})

    def test_dotted_array_of_tables(self):
        src = '[agent]\nname = "Lock"\n\n[[agent.menu]]\ncode = "run"\n\n[[agent.menu]]\ncode = "stop"\n'
        self.assertEqual(
            mt.loads(src),
            {"agent": {"name": "Lock", "menu": [{"code": "run"}, {"code": "stop"}]}},
        )

    def test_redefined_table_raises(self):
        src = "[a]\nx = \"1\"\n[a]\ny = \"2\"\n"
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads(src)

    def test_duplicate_key_raises(self):
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads('x = "1"\nx = "2"\n')


class TestUnsupportedFeaturesRaise(unittest.TestCase):
    def test_numbers_raise(self):
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads("x = 42")

    def test_inline_table_raises(self):
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads('x = { a = "1" }')

    def test_literal_string_raises(self):
        with self.assertRaises(mt.TOMLDecodeError):
            mt.loads("x = 'literal'")


BMAD_WEB_SKILLS = Path.home() / "source-code" / "bmad-web" / "src" / "bmad-web-skills"


def _python_with_tomllib():
    """Return path to a Python interpreter that has stdlib tomllib, or None."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for candidate in ("python3.11", "python3.12", "python3.13", "python3.14"):
        try:
            result = subprocess.run([candidate, "-c", "import tomllib"],
                                    capture_output=True, check=False)
            if result.returncode == 0:
                return candidate
        except FileNotFoundError:
            continue
    return None


def _parse_with_tomllib(interp, file_path):
    """Parse `file_path` using the given interpreter's stdlib tomllib; return dict."""
    code = (
        "import json, sys, tomllib\n"
        "with open(sys.argv[1], 'rb') as f:\n"
        "    sys.stdout.write(json.dumps(tomllib.load(f), ensure_ascii=False))\n"
    )
    out = subprocess.check_output([interp, "-c", code, str(file_path)])
    import json
    return json.loads(out)


@unittest.skipUnless(BMAD_WEB_SKILLS.exists(), "bmad-web skills not present on this machine")
class TestRoundTripAgainstTomllib(unittest.TestCase):
    """Parse each bmad-web customize.toml with _minimal_toml and compare against
    a known-good tomllib parse from a Python 3.11+ interpreter. Skipped if no
    such interpreter is available."""

    @classmethod
    def setUpClass(cls):
        cls.interp = _python_with_tomllib()
        if cls.interp is None:
            raise unittest.SkipTest("no Python 3.11+ available for tomllib reference parse")
        cls.toml_files = sorted(BMAD_WEB_SKILLS.glob("*/customize.toml"))
        if not cls.toml_files:
            raise unittest.SkipTest("no customize.toml files found under bmad-web-skills/")

    def test_each_customize_toml(self):
        for path in self.toml_files:
            with self.subTest(file=str(path)):
                expected = _parse_with_tomllib(self.interp, path)
                actual = mt.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
