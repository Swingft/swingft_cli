"""
Shared utilities for working with identifier names across scripts.

Provides:
- split_ident: split a name into meaningful tokens (handles snake/camel/Pascal/SNAKE)
- detect_casing_style: returns one of {camel,pascal,snake,screaming,any}
- detect_casing_for_mapping: returns styles compatible with mapping script
- normalize: lowercased concatenation of tokens for similarity
- jaro_winkler: string similarity function
- STOP_TOKENS and tokens_no_stop: token helpers excluding generic terms
"""

from __future__ import annotations

from typing import List, Set


def split_ident(name: str) -> List[str]:
    parts: List[str] = []
    for chunk in name.replace('-', '_').split('_'):
        if not chunk:
            continue
        token = ''
        for c in chunk:
            if token and c.isupper() and (
                token[-1].islower()
                or (
                    len(token) > 1
                    and token[-1].isupper()
                    and (len(token) == 1 or not token[-2].isupper())
                )
            ):
                parts.append(token)
                token = c
            else:
                token += c
        if token:
            parts.append(token)
    return parts


def detect_casing_style(name: str) -> str:
    if '_' in name:
        return "screaming" if name.isupper() else "snake"
    if name and name[0].isupper():
        return "pascal"
    if name and name[0].islower():
        return "camel"
    return "any"


def detect_casing_for_mapping(name: str) -> str:
    """Compatibility layer for mapping script casing labels.

    Returns one of: "camel", "Pascal", "snake", "SNAKE", "any".
    """
    style = detect_casing_style(name)
    if style == "pascal":
        return "Pascal"
    if style == "screaming":
        return "SNAKE"
    return style


def normalize(name: str) -> str:
    toks = split_ident(name)
    return ''.join(t.lower() for t in toks) if toks else name.lower()


def jaro_winkler(s: str, t: str, p: float = 0.1, max_l: int = 4) -> float:
    if s == t:
        return 1.0
    s_len, t_len = len(s), len(t)
    if s_len == 0 or t_len == 0:
        return 0.0
    match_distance = max(s_len, t_len) // 2 - 1
    s_matches = [False] * s_len
    t_matches = [False] * t_len
    matches = 0
    transpositions = 0
    for i in range(s_len):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, t_len)
        for j in range(start, end):
            if t_matches[j]:
                continue
            if s[i] != t[j]:
                continue
            s_matches[i] = True
            t_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    k = 0
    for i in range(s_len):
        if not s_matches[i]:
            continue
        while not t_matches[k]:
            k += 1
        if s[i] != t[k]:
            transpositions += 1
        k += 1
    transpositions /= 2
    jaro = (matches / s_len + matches / t_len + (matches - transpositions) / matches) / 3.0
    l = 0
    for i in range(min(len(s), len(t), max_l)):
        if s[i] == t[i]:
            l += 1
        else:
            break
    return jaro + l * p * (1 - jaro)


STOP_TOKENS = {
    "view",
    "controller",
    "manager",
    "data",
    "list",
    "item",
    "cell",
    "service",
    "model",
    "helper",
    "util",
    "handler",
    "provider",
    "repo",
    "client",
    "server",
    "impl",
    "base",
    "common",
    "default",
    "main",
}


def tokens_no_stop(name: str) -> Set[str]:
    return {t for t in split_ident(name) if t and t.lower() not in STOP_TOKENS}



