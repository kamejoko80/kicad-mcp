"""Lightweight S-expression parser for KiCad board files.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from typing import Any


def parse_sexpr(text: str) -> Any:
    """Parse a KiCad S-expression document into nested lists and atoms."""
    tokens = _tokenize(text)
    if not tokens:
        raise ValueError("Empty S-expression input")
    value, index = _parse_node(tokens, 0)
    if index != len(tokens):
        raise ValueError("Trailing tokens after S-expression root")
    return value


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char in " \t\n\r":
            index += 1
            continue
        if char == ";":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "(":
            tokens.append("(")
            index += 1
            continue
        if char == ")":
            tokens.append(")")
            index += 1
            continue
        if char == '"':
            index += 1
            parts: list[str] = []
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    parts.append(text[index + 1])
                    index += 2
                    continue
                if text[index] == '"':
                    index += 1
                    break
                parts.append(text[index])
                index += 1
            tokens.append("".join(parts))
            continue

        start = index
        while index < length and text[index] not in ' \t\n\r()";':
            index += 1
        tokens.append(text[start:index])

    return tokens


def _parse_node(tokens: list[str], index: int) -> tuple[Any, int]:
    token = tokens[index]
    if token == "(":
        items: list[Any] = []
        index += 1
        while index < len(tokens) and tokens[index] != ")":
            value, index = _parse_node(tokens, index)
            items.append(value)
        if index >= len(tokens) or tokens[index] != ")":
            raise ValueError("Unterminated S-expression list")
        return items, index + 1

    return _parse_atom(token), index + 1


def _parse_atom(token: str) -> str | int | float:
    if not token:
        return token
    try:
        if token.lstrip("-").isdigit():
            return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token


def sexpr_atoms(node: Any) -> list[Any]:
    """Return child atoms/lists after the leading symbol in an S-expression list."""
    if not isinstance(node, list) or not node:
        return []
    return node[1:]


def sexpr_symbol(node: Any, default: str | None = None) -> str | None:
    if not isinstance(node, list) or not node:
        return default
    head = node[0]
    return head if isinstance(head, str) else default


def find_child(node: Any, name: str) -> Any | None:
    if not isinstance(node, list):
        return None
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == name:
            return child
    return None


def find_children(node: Any, name: str) -> list[Any]:
    if not isinstance(node, list):
        return []
    return [
        child
        for child in node[1:]
        if isinstance(child, list) and child and child[0] == name
    ]


def atom_value(node: Any, default: Any = None) -> Any:
    if isinstance(node, list) and len(node) >= 2:
        return node[1]
    return default


def atom_values(node: Any) -> list[Any]:
    if not isinstance(node, list):
        return []
    return node[1:]


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
