"""Minimal TOML parser implementing the subset BMad customize.toml/config.toml
files actually use. Loaded as a fallback on Python 3.9/3.10 where the
stdlib `tomllib` module isn't available; on 3.11+ tomllib is preferred.

Supported subset:
  - Tables `[section]` and dotted `[section.sub]`
  - Arrays of tables `[[section]]` (including dotted)
  - Basic single-line strings `"..."` with standard `\\` escapes
  - Multi-line basic strings `\"\"\"...\"\"\"`
  - Booleans `true` / `false`
  - Arrays (single- or multi-line) of any supported value type
  - Comments `# ...`
  - Bare keys: `A-Z a-z 0-9 _ -`

Anything outside this subset (numbers, datetimes, inline tables `{x=y}`,
literal strings `'...'`, dotted keys at the value level) raises
TOMLDecodeError on purpose so future customize.toml additions that exceed
the subset surface loudly rather than silently producing wrong data.
"""

import re

__all__ = ["loads", "load", "TOMLDecodeError"]


class TOMLDecodeError(ValueError):
    pass


_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_\-]+")
_HEX_RE = re.compile(r"[0-9A-Fa-f]")
_BASIC_ESCAPES = {
    "b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r",
    '"': '"', "\\": "\\",
}


def loads(s):
    if isinstance(s, bytes):
        raise TypeError("loads expects str, not bytes")
    return _Parser(s).parse()


def load(fp):
    data = fp.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return loads(data)


class _Parser:
    def __init__(self, text):
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.pos = 0
        self._defined_tables = set()

    def _eof(self):
        return self.pos >= len(self.text)

    def _peek(self, n=1):
        return self.text[self.pos:self.pos + n]

    def _line_col(self):
        line = self.text.count("\n", 0, self.pos) + 1
        col = self.pos - (self.text.rfind("\n", 0, self.pos) + 1) + 1
        return line, col

    def _error(self, msg):
        line, col = self._line_col()
        raise TOMLDecodeError(f"{msg} (line {line}, column {col})")

    def _skip_inline_ws(self):
        while not self._eof() and self.text[self.pos] in " \t":
            self.pos += 1

    def _skip_ws_and_comments(self):
        while not self._eof():
            c = self.text[self.pos]
            if c in " \t\n":
                self.pos += 1
            elif c == "#":
                nl = self.text.find("\n", self.pos)
                self.pos = len(self.text) if nl == -1 else nl
            else:
                break

    def _consume_eol(self):
        self._skip_inline_ws()
        if self._eof():
            return
        if self.text[self.pos] == "#":
            nl = self.text.find("\n", self.pos)
            self.pos = len(self.text) if nl == -1 else nl + 1
            return
        if self.text[self.pos] == "\n":
            self.pos += 1
            return
        self._error(f"unexpected character {self.text[self.pos]!r} at end of line")

    def _word_boundary(self, offset):
        idx = self.pos + offset
        if idx >= len(self.text):
            return True
        c = self.text[idx]
        return not (c.isalnum() or c in "_-")

    def _read_bare_key(self):
        m = _BARE_KEY_RE.match(self.text, self.pos)
        if not m or m.start() != self.pos:
            self._error("expected key")
        self.pos = m.end()
        return m.group(0)

    def _read_table_path(self):
        self._skip_inline_ws()
        parts = [self._read_bare_key()]
        self._skip_inline_ws()
        while self._peek(1) == ".":
            self.pos += 1
            self._skip_inline_ws()
            parts.append(self._read_bare_key())
            self._skip_inline_ws()
        return parts

    def _read_basic_string(self):
        self.pos += 1  # opening "
        out = []
        while True:
            if self._eof():
                self._error("unterminated basic string")
            c = self.text[self.pos]
            if c == '"':
                self.pos += 1
                return "".join(out)
            if c == "\n":
                self._error("newline in basic string (use triple-quoted string)")
            if c == "\\":
                out.append(self._read_escape())
            else:
                out.append(c)
                self.pos += 1

    def _read_multiline_string(self):
        self.pos += 3  # opening """
        if self._peek(1) == "\n":
            self.pos += 1  # trim immediate newline after opening
        out = []
        while True:
            if self._eof():
                self._error("unterminated multi-line string")
            if self.text[self.pos:self.pos + 3] == '"""':
                # Up to 2 additional `"` before the real close are part of the string.
                extra = 0
                while (extra < 2 and self.pos + 3 + extra < len(self.text)
                       and self.text[self.pos + 3 + extra] == '"'):
                    extra += 1
                out.append('"' * extra)
                self.pos += 3 + extra
                return "".join(out)
            c = self.text[self.pos]
            if c == "\\":
                if self._is_line_ending_backslash():
                    self.pos += 1
                    while not self._eof() and self.text[self.pos] in " \t\n":
                        self.pos += 1
                    continue
                out.append(self._read_escape())
            else:
                out.append(c)
                self.pos += 1

    def _is_line_ending_backslash(self):
        i = self.pos + 1
        while i < len(self.text) and self.text[i] in " \t":
            i += 1
        return i < len(self.text) and self.text[i] == "\n"

    def _read_escape(self):
        self.pos += 1  # consume backslash
        if self._eof():
            self._error("unterminated escape sequence")
        c = self.text[self.pos]
        if c in _BASIC_ESCAPES:
            self.pos += 1
            return _BASIC_ESCAPES[c]
        if c == "u":
            self.pos += 1
            hx = self.text[self.pos:self.pos + 4]
            if len(hx) != 4 or not all(_HEX_RE.match(ch) for ch in hx):
                self._error(r"invalid \u escape")
            self.pos += 4
            return chr(int(hx, 16))
        if c == "U":
            self.pos += 1
            hx = self.text[self.pos:self.pos + 8]
            if len(hx) != 8 or not all(_HEX_RE.match(ch) for ch in hx):
                self._error(r"invalid \U escape")
            self.pos += 8
            return chr(int(hx, 16))
        self._error(f"invalid escape sequence \\{c}")

    def _read_array(self):
        self.pos += 1  # consume [
        items = []
        while True:
            self._skip_ws_and_comments()
            if self._eof():
                self._error("unterminated array")
            if self.text[self.pos] == "]":
                self.pos += 1
                return items
            items.append(self._read_value())
            self._skip_ws_and_comments()
            if self._eof():
                self._error("unterminated array")
            c = self.text[self.pos]
            if c == ",":
                self.pos += 1
                continue
            if c == "]":
                self.pos += 1
                return items
            self._error(f"unexpected character {c!r} in array")

    def _read_value(self):
        self._skip_inline_ws()
        if self._eof():
            self._error("expected value")
        c = self.text[self.pos]
        if c == '"':
            if self.text[self.pos:self.pos + 3] == '"""':
                return self._read_multiline_string()
            return self._read_basic_string()
        if c == "[":
            return self._read_array()
        if self.text[self.pos:self.pos + 4] == "true" and self._word_boundary(4):
            self.pos += 4
            return True
        if self.text[self.pos:self.pos + 5] == "false" and self._word_boundary(5):
            self.pos += 5
            return False
        if c == "'":
            self._error("literal strings ('...') are not supported by the minimal TOML parser")
        if c == "{":
            self._error("inline tables ({...}) are not supported by the minimal TOML parser")
        if c.isdigit() or c in "+-":
            self._error("numeric values are not supported by the minimal TOML parser")
        self._error(f"unexpected character {c!r} when reading value")

    def _descend(self, root, path_prefix):
        current = root
        traversed = []
        for part in path_prefix:
            traversed.append(part)
            if part not in current:
                current[part] = {}
                current = current[part]
            elif isinstance(current[part], dict):
                current = current[part]
            elif (isinstance(current[part], list) and current[part]
                  and isinstance(current[part][-1], dict)):
                current = current[part][-1]
            else:
                self._error(f"key '{'.'.join(traversed)}' is already defined as a non-table")
        return current

    def _enter_table(self, root, path):
        current = self._descend(root, path[:-1])
        last = path[-1]
        key = tuple(path)
        if last in current:
            if not isinstance(current[last], dict):
                self._error(f"key '{'.'.join(path)}' is already defined as non-table")
            if key in self._defined_tables:
                self._error(f"table '{'.'.join(path)}' defined more than once")
        else:
            current[last] = {}
        self._defined_tables.add(key)
        return current[last]

    def _enter_array_of_tables(self, root, path):
        current = self._descend(root, path[:-1])
        last = path[-1]
        if last not in current:
            current[last] = []
        elif not isinstance(current[last], list):
            self._error(f"key '{'.'.join(path)}' is already defined as non-array")
        new_table = {}
        current[last].append(new_table)
        return new_table

    def parse(self):
        root = {}
        current = root
        while True:
            self._skip_ws_and_comments()
            if self._eof():
                return root
            if self.text[self.pos] == "[":
                if self._peek(2) == "[[":
                    self.pos += 2
                    path = self._read_table_path()
                    if self._peek(2) != "]]":
                        self._error("expected ']]'")
                    self.pos += 2
                    self._consume_eol()
                    current = self._enter_array_of_tables(root, path)
                else:
                    self.pos += 1
                    path = self._read_table_path()
                    if self._peek(1) != "]":
                        self._error("expected ']'")
                    self.pos += 1
                    self._consume_eol()
                    current = self._enter_table(root, path)
                continue
            key = self._read_bare_key()
            self._skip_inline_ws()
            if self._peek(1) != "=":
                self._error(f"expected '=' after key '{key}'")
            self.pos += 1
            value = self._read_value()
            if key in current:
                self._error(f"duplicate key '{key}'")
            current[key] = value
            self._consume_eol()
