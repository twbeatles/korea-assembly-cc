# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass

from core.config import Config


_LABEL_PATTERN = re.compile(r"[^0-9A-Za-z가-힣]+")


def normalize_committee_label(value: object) -> str:
    """위원회 표기를 비교용 라벨로 정규화한다."""
    return _LABEL_PATTERN.sub("", str(value or "")).lower()


def _normalize_xcode(value: object) -> str:
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class CommitteeCatalog:
    """현재/레거시 xcode와 약칭을 하나의 위원회 식별자로 묶는다."""

    canonical_by_label: dict[str, str]
    canonical_by_xcode: dict[str, str]

    def identity_for_name(self, name: object) -> str:
        label = normalize_committee_label(name)
        if not label:
            return ""
        return self.canonical_by_label.get(label, "")

    def identity_for_xcode(self, xcode: object) -> str:
        normalized = _normalize_xcode(xcode)
        if not normalized:
            return ""
        return self.canonical_by_xcode.get(normalized, "")

    def identity_for_row(self, row: object) -> str:
        if not isinstance(row, dict):
            return ""
        by_name = self.identity_for_name(row.get("xname", ""))
        if by_name:
            return by_name
        return self.identity_for_xcode(row.get("xcode", ""))


def build_committee_catalog() -> CommitteeCatalog:
    canonical_by_label: dict[str, str] = {}
    canonical_by_xcode: dict[str, str] = {}

    for name, code in Config.COMMITTEE_XCODE_MAP.items():
        canonical = str(name or "").strip()
        if not canonical:
            continue
        label = normalize_committee_label(canonical)
        if label:
            canonical_by_label[label] = canonical
        xcode = _normalize_xcode(code)
        if xcode:
            canonical_by_xcode[xcode] = canonical

    for alias, canonical_name in Config.COMMITTEE_ABBREVIATIONS.items():
        canonical = str(canonical_name or "").strip()
        label = normalize_committee_label(alias)
        if canonical and label:
            canonical_by_label[label] = canonical

    for xcode_value, canonical_name in Config.LEGACY_COMMITTEE_XCODES.items():
        canonical = str(canonical_name or "").strip()
        xcode = _normalize_xcode(xcode_value)
        if canonical and xcode and xcode not in canonical_by_xcode:
            canonical_by_xcode[xcode] = canonical

    return CommitteeCatalog(
        canonical_by_label=canonical_by_label,
        canonical_by_xcode=canonical_by_xcode,
    )


def canonical_committee_name(name: object) -> str:
    """약칭·구 공식명을 현재 위원회 정식 명칭으로 맞춘다."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    identity = build_committee_catalog().identity_for_name(raw)
    return identity or raw
