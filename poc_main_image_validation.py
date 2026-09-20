import json
import re
import sqlite3
from dataclasses import dataclass, asdict
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "backend" / "data" / "personal_workbench.db"
PROFILE_PATH = ROOT / ".browser-profile"
MAX_SAMPLES = 5
IMAGE_KEY_HINTS = ("image", "img", "pic", "gallery", "photo", "thumb")
REJECT_HINTS = ("avatar", "logo", "icon", "qr", "qrcode", "code", "video")
LOGIN_MARKERS = ("login.1688.com", "/member/login", "/member/signin")
VERIFY_MARKERS = ("captcha", "verify", "punish", "secdev", "slide")


@dataclass(frozen=True)
class Candidate:
    path: str
    source_key: str
    raw_url: str
    list_position: int | None
    hostname: str
    url_path: str
    has_query: bool
    query_keys: tuple[str, ...]
    has_fragment: bool
    scheme: str
    canonical_url: str
    score: int


def _tail(value: str) -> str:
    return value[-4:] if len(value) > 4 else value


def _url_shape(raw_url: str) -> dict[str, Any]:
    parsed = urlparse(raw_url.strip())
    return {
        "scheme": parsed.scheme or "protocol-relative",
        "hostname": parsed.hostname or "",
        "path": parsed.path,
        "has_query": bool(parsed.query),
        "query_keys": sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}),
        "has_fragment": bool(parsed.fragment),
    }


def normalize_main_image_url(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.path:
        return None
    return parsed._replace(fragment="").geturl()


def _looks_like_base64(value: str) -> bool:
    compact = value.replace(" ", "")
    return len(compact) > 128 and bool(re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact))


def _valid_image_url(value: Any, path: str) -> bool:
    if not isinstance(value, str) or not value.strip() or _looks_like_base64(value):
        return False
    lowered = value.casefold()
    if lowered.startswith(("data:", "blob:", "javascript:")):
        return False
    normalized = normalize_main_image_url(value)
    if normalized is None:
        return False
    context = path.casefold()
    if any(hint in context for hint in REJECT_HINTS):
        return False
    parsed = urlparse(normalized)
    image_suffix = re.search(r"\.(?:avif|gif|jpeg|jpg|png|webp)(?:$|[?&#])", parsed.path.casefold())
    return bool(image_suffix or any(hint in context for hint in IMAGE_KEY_HINTS))


def _path_text(parts: list[str]) -> str:
    return "$" + "".join(part if part.startswith("[") else f".{part}" for part in parts)


def _iter_json(value: Any, parts: list[str]):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_parts = [*parts, key_text]
            if isinstance(child, str) and _valid_image_url(child, _path_text(child_parts)):
                yield _path_text(child_parts), key_text, child, _list_position(child_parts)
            yield from _iter_json(child, child_parts)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_parts = [*parts, f"[{index}]"]
            if isinstance(child, str) and _valid_image_url(child, _path_text(child_parts)):
                source_key = next((part for part in reversed(parts) if not part.startswith("[")), "list")
                yield _path_text(child_parts), source_key, child, index
            yield from _iter_json(child, child_parts)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            yield from _iter_json(json.loads(child_value(value)), parts)
        except (json.JSONDecodeError, TypeError):
            return


def child_value(value: str) -> str:
    return unescape(value)


def _list_position(parts: list[str]) -> int | None:
    for part in reversed(parts[:-1]):
        match = re.fullmatch(r"\[(\d+)\]", part)
        if match:
            return int(match.group(1))
    return None


def _script_json_roots(html: str) -> list[Any]:
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    decoder = json.JSONDecoder()
    roots: list[Any] = []
    seen: set[str] = set()
    for script in scripts:
        for index, char in enumerate(script):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(unescape(script[index:]))
            except json.JSONDecodeError:
                continue
            marker = repr(value)[:400]
            if marker in seen:
                continue
            seen.add(marker)
            roots.append(value)
            if len(roots) >= 500:
                return roots
    return roots


def _values_for_key(value: Any, wanted_key: str):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == wanted_key:
                yield child
            yield from _values_for_key(child, wanted_key)
    elif isinstance(value, list):
        for child in value:
            yield from _values_for_key(child, wanted_key)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            yield from _values_for_key(json.loads(child_value(value)), wanted_key)
        except (json.JSONDecodeError, TypeError):
            return


def _context_value(page: Any) -> Any:
    try:
        return page.evaluate("() => window.context ?? null")
    except Exception:
        return None


def _collect_candidates(html: str, context_value: Any) -> list[Candidate]:
    observed: list[tuple[str, str, str, int | None]] = []
    for root_index, root in enumerate(_script_json_roots(html)):
        observed.extend(
            (path, key, raw, position)
            for path, key, raw, position in _iter_json(root, [f"script[{root_index}]"])
        )
    if context_value is not None:
        observed.extend(
            (path, key, raw, position)
            for path, key, raw, position in _iter_json(context_value, ["window.context"])
        )

    candidates: list[Candidate] = []
    seen: set[tuple[str, str, int | None]] = set()
    for path, key, raw, position in observed:
        normalized = normalize_main_image_url(raw)
        if normalized is None:
            continue
        shape = _url_shape(raw)
        key_score = sum(2 for hint in IMAGE_KEY_HINTS if hint in key.casefold())
        list_score = 2 if position == 0 else 0
        score = key_score + list_score
        dedupe_key = (path, normalized, position)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(
            Candidate(
                path=path,
                source_key=key,
                raw_url=raw.strip(),
                list_position=position,
                hostname=shape["hostname"],
                url_path=shape["path"],
                has_query=shape["has_query"],
                query_keys=tuple(shape["query_keys"]),
                has_fragment=shape["has_fragment"],
                scheme=shape["scheme"],
                canonical_url=normalized,
                score=score,
            )
        )
    return candidates


def _observed_offer_ids(html: str, context_value: Any) -> set[str]:
    values: list[Any] = []
    for root in _script_json_roots(html):
        values.extend(_values_for_key(root, "offerId"))
    if context_value is not None:
        values.extend(_values_for_key(context_value, "offerId"))
    return {
        str(value).strip()
        for value in values
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip()
    }


def _dom_images(page: Any) -> list[dict[str, Any]]:
    script = """
    () => Array.from(document.images).map((img, index) => {
      const rect = img.getBoundingClientRect();
      const style = getComputedStyle(img);
      const parent = img.parentElement;
      return {
        index,
        src: img.getAttribute('src') || '',
        currentSrc: img.currentSrc || '',
        naturalWidth: img.naturalWidth || 0,
        naturalHeight: img.naturalHeight || 0,
        width: rect.width,
        height: rect.height,
        top: rect.top,
        visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
        alt: img.getAttribute('alt') || '',
        id: img.id || '',
        className: typeof img.className === 'string' ? img.className : '',
        parentClassName: parent && typeof parent.className === 'string' ? parent.className : '',
        parentId: parent ? parent.id || '' : '',
      };
    })
    """
    try:
        value = page.evaluate(script)
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _eligible_dom_urls(images: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for image in images:
        if not image.get("visible"):
            continue
        if max(image.get("naturalWidth", 0), image.get("naturalHeight", 0)) < 150:
            continue
        context = " ".join(
            str(image.get(key, "")) for key in ("alt", "id", "className", "parentClassName", "parentId")
        ).casefold()
        if any(hint in context for hint in REJECT_HINTS):
            continue
        normalized = normalize_main_image_url(str(image.get("currentSrc") or image.get("src") or ""))
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _same_asset_url(structured_url: str, dom_url: str) -> bool:
    structured = urlparse(structured_url)
    dom = urlparse(dom_url)
    if structured.hostname != dom.hostname:
        return False
    if structured.path == dom.path:
        return True
    return dom.path.startswith(structured.path + "_")


def _select_candidate(candidates: list[Candidate], dom_urls: list[str]) -> Candidate | None:
    if not candidates:
        return None
    matching = [
        candidate
        for candidate in candidates
        if any(_same_asset_url(candidate.canonical_url, dom_url) for dom_url in dom_urls[:3])
    ]
    pool = matching or candidates
    return max(enumerate(pool), key=lambda item: (item[1].score, -item[0]))[1]


def _candidate_view(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    data = asdict(candidate)
    data.pop("raw_url", None)
    data.pop("canonical_url", None)
    data["raw_url_shape"] = _url_shape(candidate.raw_url)
    data["canonical_url_shape"] = _url_shape(candidate.canonical_url)
    data["_raw_exact"] = candidate.raw_url
    data["_canonical_exact"] = candidate.canonical_url
    return data


def _candidate_summary(candidate: Candidate | None) -> dict[str, Any] | None:
    data = _candidate_view(candidate)
    if data is None:
        return None
    return {
        key: data[key]
        for key in (
            "path",
            "source_key",
            "list_position",
            "hostname",
            "url_path",
            "scheme",
            "has_query",
            "query_keys",
            "has_fragment",
        )
    }


def _candidate_shape_stats(candidates: list[Candidate]) -> dict[str, Any]:
    scheme_counts: dict[str, int] = {}
    query_keys: set[str] = set()
    for candidate in candidates:
        scheme_counts[candidate.scheme] = scheme_counts.get(candidate.scheme, 0) + 1
        query_keys.update(candidate.query_keys)
    return {
        "scheme_counts": scheme_counts,
        "query_candidate_count": sum(candidate.has_query for candidate in candidates),
        "fragment_candidate_count": sum(candidate.has_fragment for candidate in candidates),
        "query_keys": sorted(query_keys),
    }


def _access_state(page: Any, status: int | None) -> str:
    url = str(getattr(page, "url", ""))
    title = ""
    try:
        title = page.title()
    except Exception:
        pass
    lowered = f"{url} {title}".casefold()
    if any(marker in lowered for marker in VERIFY_MARKERS) or title in {"安全验证", "滑动验证", "验证码"}:
        return "verification_required"
    if any(marker in lowered for marker in LOGIN_MARKERS) or title.casefold() in {"登录", "1688登录", "login"}:
        return "login_required"
    if status is not None and status >= 400:
        return f"page_unavailable_{status}"
    return "ok"


def _collect_once(context: Any, sample: dict[str, Any]) -> dict[str, Any]:
    page = context.new_page()
    try:
        try:
            response = page.goto(sample["url"], wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)
        except (PlaywrightTimeoutError, TimeoutError):
            return {"id": sample["id"], "offer_id_tail": _tail(sample["offer_id"]), "status": "navigation_timeout"}
        except PlaywrightError as error:
            return {"id": sample["id"], "offer_id_tail": _tail(sample["offer_id"]), "status": f"navigation_failed:{type(error).__name__}"}

        status = response.status if response is not None else None
        access = _access_state(page, status)
        if access != "ok":
            return {"id": sample["id"], "offer_id_tail": _tail(sample["offer_id"]), "status": access}

        html = page.content()
        context_value = _context_value(page)
        offer_ids = _observed_offer_ids(html, context_value)
        if sample["offer_id"] not in offer_ids:
            return {
                "id": sample["id"],
                "offer_id_tail": _tail(sample["offer_id"]),
                "status": "target_not_confirmed",
                "observed_offer_id_tails": sorted({_tail(value) for value in offer_ids})[:10],
            }
        candidates = _collect_candidates(html, context_value)
        dom_images = _dom_images(page)
        dom_urls = _eligible_dom_urls(dom_images)
        selected = _select_candidate(candidates, dom_urls)
        first_candidates = candidates[:20]
        exact_match = bool(selected and selected.canonical_url in dom_urls[:3])
        equivalent_match = bool(
            selected
            and any(_same_asset_url(selected.canonical_url, dom_url) for dom_url in dom_urls[:3])
        )
        return {
            "id": sample["id"],
            "offer_id_tail": _tail(sample["offer_id"]),
            "status": "ok",
            "candidate_count": len(candidates),
            "candidate_shape_stats": _candidate_shape_stats(candidates),
            "candidate_source_keys": sorted({candidate.source_key for candidate in candidates}),
            "candidate_path_examples": [
                _candidate_summary(candidate) for candidate in first_candidates[:5]
            ],
            "selected_candidate": _candidate_view(selected),
            "dom_visible_image_count": len(dom_urls),
            "dom_image_shapes": [_url_shape(url) for url in dom_urls[:5]],
            "matches_dom": exact_match or equivalent_match,
            "dom_match_status": (
                "same"
                if exact_match
                else "different-but-equivalent"
                if equivalent_match
                else "different"
                if selected
                else "unknown"
            ),
        }
    finally:
        page.close()


def _samples() -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, offer_id, url FROM competitors WHERE is_active = 1 ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return [{"id": row[0], "offer_id": str(row[1]), "url": row[2]} for row in rows[:MAX_SAMPLES]]


def _repeat_label(first: dict[str, Any], second: dict[str, Any]) -> str:
    first_selected = first.get("selected_candidate")
    second_selected = second.get("selected_candidate")
    if not first_selected or not second_selected:
        return "cannot-determine"
    if first_selected.get("_canonical_exact") == second_selected.get("_canonical_exact"):
        return "same"
    if _same_asset_url(first_selected.get("_canonical_exact", ""), second_selected.get("_canonical_exact", "")):
        return "different-but-equivalent"
    return "different"


def main() -> None:
    assert normalize_main_image_url("//cbu01.alicdn.com/img/a.jpg#fragment") == "https://cbu01.alicdn.com/img/a.jpg"
    assert normalize_main_image_url("data:image/png;base64,abc") is None
    assert normalize_main_image_url("ftp://cbu01.alicdn.com/img/a.jpg") is None
    samples = _samples()
    if not PROFILE_PATH.is_dir():
        raise SystemExit(f"PROFILE_MISSING: {PROFILE_PATH}")
    results: list[dict[str, Any]] = []
    repeat_targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_PATH),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox"],
        )
        try:
            for sample in samples:
                result = _collect_once(context, sample)
                results.append(result)
                if result.get("status") == "ok" and len(repeat_targets) < 2:
                    repeat_targets.append((sample, result))
            for sample, first in repeat_targets:
                second = _collect_once(context, sample)
                first_selected = first.get("selected_candidate") or {}
                second_selected = second.get("selected_candidate") or {}
                first["repeat_visit"] = {
                    "raw_stable": first_selected.get("_raw_exact") == second_selected.get("_raw_exact"),
                    "canonical_stable": first_selected.get("_canonical_exact") == second_selected.get("_canonical_exact"),
                    "classification": _repeat_label(first, second),
                    "second_status": second.get("status"),
                }
        finally:
            context.close()

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if not key.startswith("_")}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    print(json.dumps(scrub({"sample_count": len(samples), "results": results}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
