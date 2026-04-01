# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

from importlib import import_module
from typing import Any

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)

from core import utils
from core.logging_utils import logger
from core.models import ObservedSubtitleRow
from ui.main_window_impl.contracts import CaptureDomHost


def _capture_public() -> Any:
    return import_module("ui.main_window_capture")


CaptureDomBase = object


class MainWindowCaptureDomMixin(CaptureDomBase):
    def _build_subtitle_selector_candidates(
        self, primary_selector: str, extras: list[str] | None = None
    ) -> list[str]:
        """우선순위가 반영된 자막 CSS 셀렉터 후보 목록을 생성한다."""
        candidates = []

        def _add(sel: str) -> None:
            if not isinstance(sel, str):
                return
            norm = sel.strip()
            if not norm or norm in candidates:
                return
            candidates.append(norm)

        _add(primary_selector or "")
        for sel in [
            "#viewSubtit .smi_word:last-child",
            "#viewSubtit .smi_word",
            "#viewSubtit .incont",
            "#viewSubtit span",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        ]:
            _add(sel)

        if extras:
            for sel in extras:
                _add(sel)

        broad_selectors = {
            "#viewSubtit .incont",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        }
        priority = {
            "#viewSubtit .smi_word:last-child": 0,
            "#viewSubtit .smi_word": 1,
            "#viewSubtit span": 2,
            "#viewSubtit .incont": 7,
            "#viewSubtit": 8,
            ".subtitle_area": 9,
            ".ai_subtitle": 10,
            "[class*='subtitle']": 11,
        }
        primary_norm = (primary_selector or "").strip()
        order_map = {sel: idx for idx, sel in enumerate(candidates)}

        def _weight(sel: str) -> tuple[int, int]:
            original_idx = order_map.get(sel, 999)
            if sel in priority:
                return priority[sel], original_idx
            if sel == primary_norm and sel not in broad_selectors:
                return 3, original_idx
            if sel in broad_selectors:
                return 12, original_idx
            return 4, original_idx

        return sorted(candidates, key=_weight)

    def _read_subtitle_probe_by_selectors(
        self,
        driver,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
        filter_unconfirmed_enabled: bool = True,
    ) -> dict[str, Any]:
        """Return structured subtitle probe data aligned with the Chrome extension."""

        def _normalize_rows(rows: object) -> list[ObservedSubtitleRow]:
            observed: list[ObservedSubtitleRow] = []
            if not isinstance(rows, list):
                return observed
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = self._normalize_subtitle_text_for_option(
                    row.get("text", "")
                ).strip()
                if not utils.compact_subtitle_text(text):
                    continue
                node_key = str(row.get("nodeKey", "") or "").strip()
                if not node_key:
                    continue
                speaker_channel = str(row.get("speakerChannel") or "unknown")
                if speaker_channel not in ("primary", "secondary", "unknown"):
                    speaker_channel = "unknown"
                observed.append(
                    ObservedSubtitleRow(
                        node_key=node_key,
                        text=text,
                        speaker_color=str(row.get("speakerColor", "") or ""),
                        speaker_channel=speaker_channel,
                        unstable_key=bool(row.get("unstableKey", False)),
                    )
                )
            return observed

        def _probe_in_current_context() -> dict[str, Any]:
            try:
                result = driver.execute_script(
                    """
                    return (function(selectorsArg, filterUnconfirmedArg) {
                        function normalizeText(value) {
                            return String(value || '').replace(/\\s+/g, ' ').trim();
                        }
                        function compactText(value) {
                            return normalizeText(value).replace(/\\s+/g, '');
                        }
                        function queryAllSafe(selector) {
                            try { return Array.from(document.querySelectorAll(selector)); }
                            catch (e) { return []; }
                        }
                        function queryOneSafe(selector) {
                            try { return document.querySelector(selector); }
                            catch (e) { return null; }
                        }
                        function normalizeSpeakerColor(color) {
                            var probe = document.createElement('span');
                            probe.style.color = String(color || '').trim();
                            (document.body || document.documentElement).appendChild(probe);
                            var normalized = window.getComputedStyle(probe).color;
                            probe.remove();
                            return normalized;
                        }
                        function classifySpeakerChannel(color) {
                            var normalized = normalizeSpeakerColor(color);
                            if (normalized === 'rgb(35, 124, 147)') return 'primary';
                            if (normalized === 'rgb(30, 30, 30)') return 'secondary';
                            return 'unknown';
                        }
                        function hasOpaqueBackground(backgroundColor) {
                            var normalized = String(backgroundColor || '').replace(/\\s+/g, '').toLowerCase();
                            return Boolean(normalized) && normalized !== 'transparent' && normalized !== 'rgba(0,0,0,0)';
                        }
                        function isConfirmedSubtitleNode(node) {
                            var bg = window.getComputedStyle(node).backgroundColor;
                            if (hasOpaqueBackground(bg)) return false;
                            var descendants = Array.from(node.querySelectorAll('*'));
                            var limit = Math.min(descendants.length, 48);
                            for (var i = 0; i < limit; i++) {
                                var childBg = window.getComputedStyle(descendants[i]).backgroundColor;
                                if (hasOpaqueBackground(childBg)) return false;
                            }
                            return true;
                        }
                        function normalizeRowQuery(selector) {
                            return String(selector || '')
                                .replace(/:last-child/g, '')
                                .replace(/:last-of-type/g, '')
                                .trim();
                        }
                        function getSmiWordNodes(selector) {
                            var query = normalizeRowQuery(selector) || '#viewSubtit .smi_word';
                            var nodes = queryAllSafe(query);
                            return nodes.length ? nodes : queryAllSafe('#viewSubtit .smi_word');
                        }
                        function extractClassNodeKey(node) {
                            var classes = String(node.className || '')
                                .split(/\\s+/)
                                .map(function(token) { return token.trim(); })
                                .filter(function(token) { return token && token !== 'smi_word'; });
                            return classes[0] || '';
                        }
                        function extractAttributeNodeKey(node) {
                            var candidates = [node.getAttribute('data-id'), node.getAttribute('data-key'), node.id];
                            for (var i = 0; i < candidates.length; i++) {
                                var candidate = String(candidates[i] || '').trim();
                                if (candidate) return candidate;
                            }
                            return '';
                        }
                        function ensureGeneratedNodeKey(node) {
                            if (!node.dataset.assemblyRowKey) {
                                node.dataset.assemblyRowKey = 'row_' + Math.random().toString(36).slice(2, 9) + '_' + Date.now();
                            }
                            return node.dataset.assemblyRowKey;
                        }
                        function readObservedRows(selector) {
                            var rows = [];
                            var nodes = getSmiWordNodes(selector);
                            var classKeyCounts = new Map();
                            nodes.forEach(function(node) {
                                var classKey = extractClassNodeKey(node);
                                if (!classKey) return;
                                classKeyCounts.set(classKey, (classKeyCounts.get(classKey) || 0) + 1);
                            });
                            nodes.forEach(function(node) {
                                if (filterUnconfirmedArg && !isConfirmedSubtitleNode(node)) {
                                    return;
                                }
                                var text = normalizeText(node.innerText || node.textContent || '');
                                if (!compactText(text)) return;
                                var classNodeKey = extractClassNodeKey(node);
                                var attrNodeKey = extractAttributeNodeKey(node);
                                var uniqueClassKey = Boolean(classNodeKey) && classKeyCounts.get(classNodeKey) === 1;
                                var nodeKey = uniqueClassKey
                                    ? 'class:' + classNodeKey
                                    : (attrNodeKey ? 'attr:' + attrNodeKey : ensureGeneratedNodeKey(node));
                                var speakerNode = node.querySelector('span') || node.querySelector('[style*="color"]') || node;
                                var speakerColor = normalizeSpeakerColor(window.getComputedStyle(speakerNode).color);
                                var row = {
                                    nodeKey: nodeKey,
                                    text: text,
                                    speakerColor: speakerColor,
                                    speakerChannel: classifySpeakerChannel(speakerColor),
                                    unstableKey: !uniqueClassKey && !attrNodeKey
                                };
                                var previous = rows.length ? rows[rows.length - 1] : null;
                                if (
                                    previous &&
                                    compactText(previous.text) === compactText(row.text) &&
                                    (previous.nodeKey === row.nodeKey || (previous.unstableKey && row.unstableKey))
                                ) {
                                    rows[rows.length - 1] = row;
                                    return;
                                }
                                rows.push(row);
                            });
                            return rows;
                        }
                        function buildPreview(rows) {
                            return rows.slice(-3).map(function(row) { return row.text; }).filter(Boolean).join(' ').trim();
                        }
                        function normalizeContainerText(node) {
                            var raw = node ? (node.innerText || node.textContent || '') : '';
                            var text = normalizeText(raw);
                            if (!text) return '';
                            if (text.length <= 400) return text;
                            var lines = String(raw || '').split('\\n').map(normalizeText).filter(Boolean);
                            return lines.slice(-3).join(' ');
                        }
                        function shouldBlockContainerFallback() {
                            if (!filterUnconfirmedArg) return false;
                            var smiNodes = queryAllSafe('#viewSubtit .smi_word');
                            if (!smiNodes.length) return false;
                            return readObservedRows('#viewSubtit .smi_word').length === 0;
                        }
                        var selectors = Array.isArray(selectorsArg) ? selectorsArg : [];
                        var blockContainerFallback = shouldBlockContainerFallback();
                        var fallbackSelectors = [
                            '#viewSubtit .incont',
                            '#viewSubtit',
                            '.subtitle_area',
                            '.ai_subtitle',
                            "[class*='subtitle']"
                        ];
                        for (var i = 0; i < selectors.length; i++) {
                            var selector = String(selectors[i] || '').trim();
                            if (!selector) continue;
                            if (selector.indexOf('.smi_word') >= 0) {
                                var rows = readObservedRows(selector);
                                var preview = buildPreview(rows);
                                if (preview) {
                                    return { text: preview, matchedSelector: selector, found: true, rows: rows, sourceMode: 'smi-window' };
                                }
                                continue;
                            }
                            if (blockContainerFallback) continue;
                            var node = queryOneSafe(selector);
                            if (!node) continue;
                            var text = normalizeContainerText(node);
                            if (!text) continue;
                            return { text: text, matchedSelector: selector, found: true, rows: [], sourceMode: 'container' };
                        }
                        if (!blockContainerFallback) {
                            for (var j = 0; j < fallbackSelectors.length; j++) {
                                var fallbackSelector = fallbackSelectors[j];
                                var fallbackNode = queryOneSafe(fallbackSelector);
                                if (!fallbackNode) continue;
                                var fallbackText = normalizeContainerText(fallbackNode);
                                if (!fallbackText) continue;
                                return { text: fallbackText, matchedSelector: fallbackSelector, found: true, rows: [], sourceMode: 'container' };
                            }
                        }
                        return { text: '', matchedSelector: '', found: false, rows: [], sourceMode: '' };
                    })(arguments[0], arguments[1]);
                    """,
                    selectors,
                    bool(filter_unconfirmed_enabled),
                )
            except Exception as e:
                self._raise_if_recoverable_webdriver_error(e, "subtitle probe error")
                logger.debug("subtitle probe error: %s", e)
                return {
                    "text": "",
                    "matched_selector": "",
                    "found": False,
                    "rows": [],
                    "source_mode": "",
                }
            result = result or {}
            return {
                "text": self._normalize_subtitle_text_for_option(
                    result.get("text", "")
                ).strip(),
                "matched_selector": str(result.get("matchedSelector", "") or ""),
                "found": bool(result.get("found", False)),
                "rows": _normalize_rows(result.get("rows", [])),
                "source_mode": str(result.get("sourceMode", "") or ""),
            }

        frame_paths: list[tuple[int, ...]] = []
        if preferred_frame_path:
            frame_paths.append(preferred_frame_path)
        frame_paths.append(())
        for frame_path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
            if frame_path not in frame_paths:
                frame_paths.append(frame_path)

        for frame_path in frame_paths:
            try:
                if frame_path:
                    if not self._switch_to_frame_path(driver, frame_path):
                        continue
                else:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                result = _probe_in_current_context()
                if result.get("found"):
                    self._last_subtitle_frame_path = frame_path
                    result["frame_path"] = frame_path
                    return result
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

        return {
            "text": "",
            "matched_selector": "",
            "found": False,
            "rows": [],
            "source_mode": "",
            "frame_path": (),
        }

    def _read_subtitle_text_by_selectors(
        self,
        driver,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
    ) -> tuple[str, str, bool]:
        """여러 셀렉터를 순차 시도해 자막 텍스트를 읽는다."""
        capture_mod = _capture_public()

        def _read_in_current_context() -> tuple[str, str, bool]:
            def _read_smi_word_window(sel: str) -> tuple[str, bool]:
                try:
                    rows = driver.execute_script(
                        """
                        return (function(selectorArg) {
                            function normalizeText(v) {
                                return String(v || '').replace(/\\s+/g, ' ').trim();
                            }
                            var q = String(selectorArg || '').trim();
                            if (!q) q = '#viewSubtit .smi_word';
                            q = q.replace(/:last-child/g, '').replace(/:last-of-type/g, '');
                            var nodes = [];
                            try { nodes = Array.from(document.querySelectorAll(q)); } catch (e) {}
                            if ((!nodes || !nodes.length) && q !== '#viewSubtit .smi_word') {
                                try { nodes = Array.from(document.querySelectorAll('#viewSubtit .smi_word')); } catch (e) {}
                            }
                            return nodes.map(function(el, idx) {
                                var cls = String(el.className || '');
                                var idPart = cls.replace(/\\bsmi_word\\b/g, '').trim();
                                var text = normalizeText(el.innerText || el.textContent || '');
                                return { id: idPart || String(idx), text: text };
                            });
                        })(arguments[0]);
                        """,
                        sel,
                    )
                except Exception as e:
                    self._raise_if_recoverable_webdriver_error(e, f"smi_word 수집 오류 ({sel})")
                    logger.debug("smi_word 수집 오류 (%s): %s", sel, e)
                    return "", False

                if not isinstance(rows, list) or not rows:
                    return "", False

                normalized_rows: list[tuple[str, str, str]] = []
                for row in rows:
                    if isinstance(row, dict):
                        row_text = self._normalize_subtitle_text_for_option(
                            row.get("text", "")
                        )
                        row_id = str(row.get("id", "")).strip()
                    else:
                        row_text = self._normalize_subtitle_text_for_option(row)
                        row_id = ""
                    if not row_text:
                        continue

                    row_compact = utils.compact_subtitle_text(row_text)
                    if not row_compact:
                        continue

                    if normalized_rows and normalized_rows[-1][2] == row_compact:
                        normalized_rows[-1] = (row_id, row_text, row_compact)
                    else:
                        normalized_rows.append((row_id, row_text, row_compact))

                if not normalized_rows:
                    return "", False

                tail_texts = [t for _, t, _ in normalized_rows[-3:]]
                window_text = " ".join(tail_texts).strip()
                if not window_text:
                    return "", False
                return window_text, True

            for sel in selectors:
                if ".smi_word" in sel:
                    smi_text, smi_found = _read_smi_word_window(sel)
                    if smi_found:
                        return smi_text, sel, True

                try:
                    element = driver.find_element(capture_mod.By.CSS_SELECTOR, sel)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                except Exception as e:
                    self._raise_if_recoverable_webdriver_error(e, f"셀렉터 조회 오류 ({sel})")
                    logger.debug("셀렉터 조회 오류 (%s): %s", sel, e)
                    continue

                try:
                    text = (element.text or "").strip()
                except StaleElementReferenceException:
                    continue
                except Exception as e:
                    self._raise_if_recoverable_webdriver_error(
                        e, f"셀렉터 텍스트 조회 오류 ({sel})"
                    )
                    text = ""
                return self._normalize_subtitle_text_for_option(text), sel, True
            return "", "", False

        if preferred_frame_path:
            try:
                if self._switch_to_frame_path(driver, preferred_frame_path):
                    result = _read_in_current_context()
                    if result[2]:
                        self._last_subtitle_frame_path = preferred_frame_path
                        return result
            finally:
                driver.switch_to.default_content()

        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        result = _read_in_current_context()
        if result[2]:
            self._last_subtitle_frame_path = ()
            return result

        for frame_path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
            try:
                if self._switch_to_frame_path(driver, frame_path):
                    result = _read_in_current_context()
                    if result[2]:
                        self._last_subtitle_frame_path = frame_path
                        return result
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

        return "", "", False

    def _switch_to_frame_path(self, driver, frame_path: tuple[int, ...]) -> bool:
        """frame index 경로로 이동한다. 실패 시 False."""
        capture_mod = _capture_public()
        try:
            driver.switch_to.default_content()
        except Exception as e:
            self._raise_if_recoverable_webdriver_error(e, "frame 기본 문맥 전환 실패")
            return False

        for idx in frame_path:
            try:
                frames = driver.find_elements(capture_mod.By.CSS_SELECTOR, "iframe,frame")
                if idx < 0 or idx >= len(frames):
                    return False
                driver.switch_to.frame(frames[idx])
            except Exception as e:
                self._raise_if_recoverable_webdriver_error(
                    e, f"frame 경로 전환 실패 ({frame_path})"
                )
                return False
        return True

    def _iter_frame_paths(
        self, driver, max_depth: int = 3, max_frames: int = 60
    ) -> list[tuple[int, ...]]:
        """중첩 iframe/frame 경로 목록을 반환한다."""
        capture_mod = _capture_public()
        paths: list[tuple[int, ...]] = []

        def _walk(path: tuple[int, ...], depth: int) -> None:
            if len(paths) >= max_frames or depth > max_depth:
                return
            if not self._switch_to_frame_path(driver, path):
                return
            try:
                frames = driver.find_elements(capture_mod.By.CSS_SELECTOR, "iframe,frame")
            except Exception as e:
                self._raise_if_recoverable_webdriver_error(
                    e, f"frame 목록 조회 실패 ({path})"
                )
                return

            for idx in range(len(frames)):
                child = path + (idx,)
                paths.append(child)
                if len(paths) >= max_frames:
                    return
                _walk(child, depth + 1)

        try:
            _walk((), 0)
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        return paths
