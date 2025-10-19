from __future__ import annotations

from pathlib import Path
from typing import Optional, List


class ParseState:
    NORMAL = 1
    SINGLE_LINE_COMMENT = 2
    MULTI_LINE_COMMENT = 3
    STRING = 4
    MULTILINE_STRING = 5
    STRING_ESCAPE = 6
    MULTILINE_STRING_ESCAPE = 7
    REGEX_LITERAL = 8
    EXTENDED_REGEX = 9
    IN_INTERPOLATION = 10


class StateContext:
    def __init__(self, state: int, hash_count: int = 0, quote_count: int = 0):
        self.state = state
        self.hash_count = hash_count
        self.quote_count = quote_count


class SwiftCommentRemover:
    def __init__(self):
        self.source = ""
        self.result: List[str] = []
        self.i = 0
        self.length = 0

        self.current_state = ParseState.NORMAL
        self.state_stack: List[StateContext] = []

        self.nesting_level = 0
        self.current_hash_count = 0
        self.current_quote_count = 0

        self.interpolation_depth = 0
        self.brace_depth = 0
        self.bracket_depth = 0

        self.line_had_content = False

    def remove_comments(self, source: str) -> str:
        self.source = source
        self.result = []
        self.i = 0
        self.length = len(source)
        self.state_stack = []
        self.current_state = ParseState.NORMAL
        self.nesting_level = 0
        self.current_hash_count = 0
        self.current_quote_count = 0
        self.interpolation_depth = 0
        self.brace_depth = 0
        self.bracket_depth = 0
        self.line_had_content = False

        while self.i < self.length:
            self._process_current_char()
            self.i += 1

        return ''.join(self.result)

    def _process_current_char(self):
        handlers = {
            ParseState.NORMAL: self._handle_normal,
            ParseState.SINGLE_LINE_COMMENT: self._handle_single_comment,
            ParseState.MULTI_LINE_COMMENT: self._handle_multi_comment,
            ParseState.STRING: self._handle_string,
            ParseState.STRING_ESCAPE: self._handle_string_escape,
            ParseState.MULTILINE_STRING: self._handle_multiline_string,
            ParseState.MULTILINE_STRING_ESCAPE: self._handle_multiline_string_escape,
            ParseState.REGEX_LITERAL: self._handle_regex,
            ParseState.EXTENDED_REGEX: self._handle_extended_regex,
            ParseState.IN_INTERPOLATION: self._handle_in_interpolation,
        }
        handler = handlers.get(self.current_state)
        if handler:
            handler()

    def _peek(self, offset: int = 1) -> Optional[str]:
        pos = self.i + offset
        return self.source[pos] if pos < self.length else None

    def _count_char(self, char: str, start_offset: int = 0) -> int:
        count = 0
        pos = self.i + start_offset
        while pos < self.length and self.source[pos] == char:
            count += 1
            pos += 1
        return count

    def _is_regex_context(self) -> bool:
        pos = self.i - 1
        while pos >= 0 and self.source[pos].isspace():
            pos -= 1
        if pos < 0:
            return True
        char = self.source[pos]
        regex_preceding = {'=', '(', ',', '[', ':', '{', '!', '&', '|', '^', '+', '-', '*', '%', '<', '>', '~', ';'}
        if char in regex_preceding:
            return True
        for keyword in ['return', 'where']:
            keyword_len = len(keyword)
            if pos >= keyword_len - 1:
                start = pos - keyword_len + 1
                if self.source[start:pos + 1] == keyword:
                    if start == 0 or not self.source[start - 1].isalnum():
                        return True
        return False

    def _append(self, text: str):
        self.result.append(text)

    def _current_char(self) -> str:
        return self.source[self.i]

    def _revert_to_previous_state(self):
        self.current_hash_count = 0
        self.current_quote_count = 0
        if self.interpolation_depth > 0:
            self.current_state = ParseState.IN_INTERPOLATION
        else:
            self.current_state = ParseState.NORMAL

    def _remove_trailing_spaces(self):
        while self.result and self.result[-1] in (' ', '\t'):
            self.result.pop()

    def _is_line_only_whitespace_before_comment(self):
        pos = self.i - 1
        while pos >= 0:
            ch = self.source[pos]
            if ch == '\n':
                return True
            if ch not in (' ', '\t'):
                return False
            pos -= 1
        return True

    def _handle_normal_or_interpolation(self):
        char = self._current_char()
        next_char = self._peek()

        if char == '/' and next_char == '/':
            self._remove_trailing_spaces()
            self.line_had_content = not self._is_line_only_whitespace_before_comment()
            self.current_state = ParseState.SINGLE_LINE_COMMENT
            self.i += 1
            return
        if char == '/' and next_char == '*':
            self._remove_trailing_spaces()
            self.line_had_content = not self._is_line_only_whitespace_before_comment()
            self.current_state = ParseState.MULTI_LINE_COMMENT
            self.nesting_level = 1
            self.i += 1
            return

        if char == '#':
            hash_count = self._count_char('#')
            next_after_hash = self._peek(hash_count)
            if next_after_hash == '"':
                quote_count = self._count_char('"', hash_count)
                state = ParseState.MULTILINE_STRING if quote_count >= 3 else ParseState.STRING
                self._enter_string_state(state, hash_count, quote_count)
                return
            if next_after_hash == '/' and self._is_regex_context():
                self.current_state = ParseState.EXTENDED_REGEX
                self.current_hash_count = hash_count
                self._append('#' * hash_count + '/')
                self.i += hash_count
                return

        if char == '"':
            quote_count = self._count_char('"')
            state = ParseState.MULTILINE_STRING if quote_count >= 3 else ParseState.STRING
            self._enter_string_state(state, 0, quote_count)
            return

        if char == '/' and self._is_regex_context():
            self.current_state = ParseState.REGEX_LITERAL
            self._append(char)
            return

        self._append(char)

        if self.current_state == ParseState.IN_INTERPOLATION:
            if char == '(':
                self.interpolation_depth += 1
            elif char == '{':
                self.brace_depth += 1
            elif char == '[':
                self.bracket_depth += 1
            elif char == ')':
                self.interpolation_depth -= 1
                if self.interpolation_depth == 0 and self.brace_depth == 0 and self.bracket_depth == 0:
                    context = self.state_stack.pop()
                    self.current_state = context.state
                    self.current_hash_count = context.hash_count
                    self.current_quote_count = context.quote_count
            elif char == '}':
                self.brace_depth -= 1
            elif char == ']':
                self.bracket_depth -= 1

    def _handle_normal(self):
        self._handle_normal_or_interpolation()

    def _handle_in_interpolation(self):
        self._handle_normal_or_interpolation()

    def _enter_string_state(self, state: int, hash_count: int, quote_count: int):
        self.current_state = state
        self.current_hash_count = hash_count
        self.current_quote_count = quote_count if state == ParseState.MULTILINE_STRING else 1
        delimiters = '#' * hash_count + '"' * self.current_quote_count
        self._append(delimiters)
        self.i += len(delimiters) - 1

    def _handle_comment_end(self):
        if self.interpolation_depth > 0:
            self.current_state = ParseState.IN_INTERPOLATION
        else:
            self.current_state = ParseState.NORMAL

    def _handle_single_comment(self):
        if self._current_char() == '\n':
            self._handle_comment_end()
            if self.line_had_content:
                self._append('\n')

    def _handle_multi_comment(self):
        char, next_char = self._current_char(), self._peek()
        if char == '/' and next_char == '*':
            self.nesting_level += 1
            self.i += 1
        elif char == '*' and next_char == '/':
            self.nesting_level -= 1
            self.i += 1
            if self.nesting_level == 0:
                self._handle_comment_end()
                if self._peek() == '\n' and not self.line_had_content:
                    self.i += 1

    def _handle_any_string(self, escape_state: int):
        char, next_char = self._current_char(), self._peek()
        if char == '\\':
            if next_char == '(':
                self._append('\\(')
                self.i += 1
                context = StateContext(self.current_state, self.current_hash_count, self.current_quote_count)
                self.state_stack.append(context)
                self.current_state = ParseState.IN_INTERPOLATION
                self.interpolation_depth = 1
                self.brace_depth = 0
                self.bracket_depth = 0
            else:
                self.current_state = escape_state
                self._append(char)
            return

        is_closing_quote = False
        if char == '"':
            end_quote_count = self._count_char('"')
            if end_quote_count >= self.current_quote_count:
                if self.current_hash_count > 0:
                    if self._count_char('#', end_quote_count) >= self.current_hash_count:
                        is_closing_quote = True
                else:
                    is_closing_quote = True

        if is_closing_quote:
            delimiters = '"' * self.current_quote_count + '#' * self.current_hash_count
            self._append(delimiters)
            self.i += len(delimiters) - 1
            self._revert_to_previous_state()
        else:
            self._append(char)

    def _handle_string(self):
        self._handle_any_string(ParseState.STRING_ESCAPE)

    def _handle_multiline_string(self):
        self._handle_any_string(ParseState.MULTILINE_STRING_ESCAPE)

    def _handle_string_escape(self):
        self._append(self._current_char())
        self.current_state = ParseState.STRING

    def _handle_multiline_string_escape(self):
        self._append(self._current_char())
        self.current_state = ParseState.MULTILINE_STRING

    def _handle_regex(self):
        char, next_char = self._current_char(), self._peek()
        if char == '\\' and next_char:
            self._append(char + next_char)
            self.i += 1
        elif char == '/':
            self._append(char)
            self._revert_to_previous_state()
        else:
            self._append(char)

    def _handle_extended_regex(self):
        char = self._current_char()
        if char == '/':
            if self._count_char('#', 1) >= self.current_hash_count:
                delimiters = '/' + '#' * self.current_hash_count
                self._append(delimiters)
                self.i += self.current_hash_count
                self._revert_to_previous_state()
                return
        if char == '#':
            result_len_before = len(self.result)
            spaces_before = 0
            while result_len_before > 0 and self.result[result_len_before - 1 - spaces_before] == ' ':
                spaces_before += 1
            if spaces_before > 0:
                self.result = self.result[:result_len_before - spaces_before]
            while self.i < self.length and self.source[self.i] != '\n':
                self.i += 1
            self.i -= 1
            return
        if char == '\\' and self._peek():
            self._append(char + self._peek())
            self.i += 1
            return
        self._append(char)


def strip_comments_in_place(project_dir: str) -> None:
    """Recursively remove comments from all .swift files under project_dir (in-place)."""
    root = Path(project_dir)
    if not root.exists():
        return
    remover = SwiftCommentRemover()
    for fp in root.rglob("*.swift"):
        try:
            text = fp.read_text(encoding="utf-8")
            cleaned = remover.remove_comments(text)
            if cleaned != text:
                fp.write_text(cleaned, encoding="utf-8")
        except Exception:
            continue


