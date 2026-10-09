"""Gate 1 POC: read only the visible official-assistant panel and explicit page regions."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / ".browser-profile"
DB_PATH = ROOT / "backend" / "data" / "personal_workbench.db"
SCREENSHOT_PATH = Path(__file__).resolve().parent / "a19-top-panel.png"
A19_GROUP = "A19磁吸暖手宝"
ORIGINAL_FIVE = ("1079906223307", "1080864798243", "1083985416394", "1082904060172", "1081895898799")
ASSISTANT_HEADING = "1688官方采购助手"
TOP_FIELDS = {
    "上架时间": ("上架时间",),
    "月成交": ("月成交",),
    "月代销": ("月代销",),
    "年成交件数": ("年成交件数",),
    "年成交笔数": ("年成交笔数",),
    "评论数": ("评论数",),
    "好评率": ("好评率",),
    "揽收率": ("揽收率",),
}
TAGS = ("新品", "人气新品", "首发新品", "超级新品", "严选", "跨境", "镇店之宝", "哇偶定制")
PLACEHOLDERS = {"-", "—", "–", "--", "暂无", "未显示"}
LOADING_MARKERS = ("加载中", "正在加载", "数据加载中", "loading", "读取中", "获取中")
LOGIN_MARKERS = ("login.1688.com", "/member/signin", "/member/login")
VERIFY_MARKERS = ("captcha", "verify", "punish", "secdev", "slide")


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8), "Asia/Shanghai")).isoformat(timespec="seconds")


def emit(data: dict[str, object]) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def read_offer(offer_id: str) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, offer_id, url, title, shop_name, group_role, ownership, group_id "
            "FROM competitors WHERE offer_id = ? AND is_active = 1",
            (offer_id,),
        ).fetchall()
    if len(row) != 1:
        raise RuntimeError(f"expected one active DB row for Offer {offer_id}; found {len(row)}")
    offer = dict(row[0])
    if not re.search(rf"/offer/{re.escape(offer_id)}(?:\.html)?(?:$|[?#])", str(offer["url"])):
        raise RuntimeError(f"DB URL does not identify Offer {offer_id}")
    return offer


def select_offers(scope: str) -> list[dict[str, object]]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        if scope == "a19":
            rows = connection.execute(
                "SELECT c.id, c.offer_id, c.url, c.title, c.shop_name, c.group_role, c.ownership, c.group_id "
                "FROM competitors c JOIN competitor_groups g ON g.id = c.group_id "
                "WHERE g.name = ? AND c.group_role = 'own' AND c.ownership = 'self' AND c.is_active = 1",
                (A19_GROUP,),
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError(f"A19 own Offer lookup must be unique; found {len(rows)}")
            offer = dict(rows[0])
            offer_id = str(offer["offer_id"])
            if not re.search(rf"/offer/{re.escape(offer_id)}(?:\.html)?(?:$|[?#])", str(offer["url"])):
                raise RuntimeError("A19 database URL does not identify its Offer ID")
            return [offer]

    return [read_offer(offer_id) for offer_id in ORIGINAL_FIVE]


def page_gate(page: object) -> str | None:
    url = str(page.url).casefold()
    title = str(page.title()).casefold()
    if any(marker in url for marker in VERIFY_MARKERS) or title in {
        "captcha", "verification", "滑动验证", "安全验证", "访问验证", "验证码"
    }:
        return "verification required"
    if any(marker in url for marker in LOGIN_MARKERS) or title in {
        "登录", "账号登录", "用户登录", "1688登录", "login", "signin", "sign in", "1688 login"
    }:
        return "login required"
    return None


def wait_for_manual_login(page: object) -> None:
    deadline = time.monotonic() + 600
    while page_gate(page) == "login required" and time.monotonic() < deadline:
        time.sleep(3)
    if page_gate(page) == "login required":
        raise RuntimeError("login required; 10 minute manual-login window expired")


def assistant_region(page: object) -> tuple[object | None, dict[str, object]]:
    headings = [
        item for item in page.get_by_text(ASSISTANT_HEADING, exact=True).all()
        if item.is_visible()
    ]
    if not headings:
        return None, {"header_visible": False, "reason": "official assistant heading absent from visible DOM"}

    heading = headings[0]
    ancestors = heading.evaluate(
        """el => {
          const out = [];
          let node = el;
          for (let depth = 0; node && node !== document.body && depth < 12; depth++, node = node.parentElement) {
            const style = getComputedStyle(node), rect = node.getBoundingClientRect();
            const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            if (!visible) continue;
            const text = (node.innerText || '').trim();
            out.push({depth, tag: node.tagName.toLowerCase(), className: String(node.className || '').slice(0, 160),
              text, containsDistribution: text.includes('分销代发'),
              labelCount: ['上架时间','月成交','月代销','年成交件数','年成交笔数','评论数','好评率','揽收率']
                .filter(label => text.includes(label)).length});
          }
          return out;
        }"""
    )
    safe = [item for item in ancestors if not item["containsDistribution"]]
    complete = [item for item in safe if item["labelCount"] == len(TOP_FIELDS)]
    chosen = (complete or safe or ancestors)[0] if (complete or safe or ancestors) else None
    if chosen is None:
        return None, {"header_visible": True, "reason": "no visible ancestor found for assistant heading"}

    locator = heading
    for _ in range(int(chosen["depth"])):
        locator = locator.locator("xpath=..")
    region_text = locator.inner_text().strip()
    verified = ASSISTANT_HEADING in region_text and "分销代发" not in region_text
    return locator, {
        "header_visible": True,
        "region_verified": verified,
        "region_depth": chosen["depth"],
        "region_tag": chosen["tag"],
        "region_class": chosen["className"],
        "region_text": region_text,
        "region_contains_distribution": "分销代发" in region_text,
        "field_labels_found": [field for field in TOP_FIELDS if field in region_text],
        "ancestor_candidates": [
            {**item, "text": str(item["text"])[:1200]}
            for item in ancestors[:8]
        ],
    }


def extract_top_fields(region_text: str) -> tuple[dict[str, dict[str, object]], bool]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in region_text.splitlines()]
    lines = [line for line in lines if line]
    loading = any(marker.casefold() in region_text.casefold() for marker in LOADING_MARKERS)
    fields: dict[str, dict[str, object]] = {}
    all_labels = {label for labels in TOP_FIELDS.values() for label in labels}
    for field, labels in TOP_FIELDS.items():
        found = None
        for index, line in enumerate(lines):
            for label in labels:
                if line == label:
                    raw = lines[index + 1] if index + 1 < len(lines) else None
                    if raw in all_labels:
                        raw = None
                    found = (raw, line + (" / " + raw if raw is not None else ""))
                    break
                if line.startswith(label + ":") or line.startswith(label + "："):
                    raw = re.sub(rf"^{re.escape(label)}\s*[:：]\s*", "", line).strip()
                    found = (raw or None, line)
                    break
            if found:
                break
        if found is None:
            status, raw, source_line = ("loading" if loading else "not_displayed"), None, None
        elif found[0] is None:
            status, raw, source_line = "read_failed", None, found[1]
        elif found[0].strip() in PLACEHOLDERS:
            status, raw, source_line = "placeholder", found[0], found[1]
        else:
            status, raw, source_line = "observed", found[0], found[1]
        fields[field] = {
            "status": status,
            "raw_value": raw,
            "source": "visible DOM inside the 1688官方采购助手 region",
            "source_line": source_line,
            "observed_at": now(),
            "failure_reason": "label visible but adjacent value missing" if status == "read_failed" else None,
        }
    return fields, loading


def read_other_sources(page: object) -> dict[str, object]:
    favorite_matches = []
    for locator in page.get_by_text("收藏", exact=True).all():
        if not locator.is_visible():
            continue
        text = locator.locator("xpath=..").inner_text().strip()
        number = re.search(r"收藏\s*[（(]?\s*([\d,]+(?:\.\d+)?(?:万)?)\s*[）)]?", text)
        favorite_matches.append({
            "raw_value": number.group(1) if number else None,
            "status": "observed" if number else "favorite_control_visible_without_count",
            "source": "visible product favorite control and its immediate parent",
            "source_text": text[:80],
            "observed_at": now(),
        })
    tags = {}
    for tag in TAGS:
        matches = [item for item in page.get_by_text(tag, exact=True).all() if item.is_visible()]
        tags[tag] = {
            "status": "observed" if matches else "not_displayed",
            "raw_value": tag if matches else None,
            "source": "visible page DOM; exact full-text match",
            "observed_at": now(),
        }
    return {
        "收藏数": favorite_matches or [{
            "raw_value": None,
            "status": "not_displayed",
            "source": "visible product favorite area",
            "observed_at": now(),
        }],
        "平台标签": tags,
    }


def same_raw_values(first: list[dict[str, object]], second: list[dict[str, object]]) -> bool:
    return [(item["status"], item["raw_value"]) for item in first] == [
        (item["status"], item["raw_value"]) for item in second
    ]


def capture(page: object, offer: dict[str, object], scope: str, screenshot: bool = False) -> dict[str, object]:
    expected = str(offer["offer_id"])
    actual = re.search(r"/offer/(\d+)(?:\.html)?", page.url)
    identity_ok = bool(actual and actual.group(1) == expected)
    region, region_info = assistant_region(page)
    region_text = str(region_info.pop("region_text", ""))
    region_info.pop("ancestor_candidates", None)
    if region is None:
        fields = {name: {"status": "read_failed", "raw_value": None, "source": "not resolved", "observed_at": now(),
                         "failure_reason": str(region_info.get("reason"))} for name in TOP_FIELDS}
        extension_loaded = False
        loading = False
    else:
        fields, loading = extract_top_fields(region_text)
        extension_loaded = any(
            worker.url.startswith("chrome-extension://kphldkppgfpjadpabfkghmjbhpcmgpdg/")
            for worker in page.context.service_workers
        )
        if screenshot:
            region.screenshot(path=str(SCREENSHOT_PATH), timeout=15_000)
    labels_visible = [name for name, data in fields.items() if data["status"] in {"placeholder", "observed", "read_failed"}]
    non_placeholder = [name for name, data in fields.items() if data["status"] == "observed"]
    return {
        "stage": "observation",
        "scope": scope,
        "offer_id": expected,
        "database_title": offer["title"],
        "database_shop": offer["shop_name"],
        "database_role": offer["group_role"],
        "observed_at": now(),
        "page_url": page.url,
        "page_offer_id": actual.group(1) if actual else None,
        "offer_identity_verified": identity_ok,
        "page_h1": page.locator("h1").first.inner_text(timeout=2_000).strip()[:160] if page.locator("h1").count() else None,
        "extension_service_worker_loaded": extension_loaded,
        "assistant_region": {
            **region_info,
            "field_labels_visible": labels_visible,
            "non_placeholder_fields": non_placeholder,
            "loading_indicator_visible": loading,
            "load_wait_seconds": 30 if all(data["status"] == "placeholder" for data in fields.values()) else 0,
        },
        "assistant_fields": fields,
        "other_allowed_sources": read_other_sources(page),
        "screenshot_path": str(SCREENSHOT_PATH) if screenshot else None,
    }


def observe(page: object, offer: dict[str, object], scope: str, screenshot: bool = False) -> dict[str, object]:
    page.goto(str(offer["url"]), wait_until="domcontentloaded", timeout=45_000)
    gate = page_gate(page)
    if gate == "verification required":
        raise RuntimeError("access_restricted: verification required; stopped without interaction")
    if gate == "login required":
        emit({"stage": "manual_login_required", "offer_id": offer["offer_id"], "reason": gate})
        wait_for_manual_login(page)
    page.locator("body").wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(5_000)
    result = capture(page, offer, scope)
    if not result["assistant_region"].get("header_visible"):
        return result

    # A dash may be a transient extension-render state. Wait on the same page, without reloads.
    deadline = time.monotonic() + 30
    while not result["assistant_region"]["non_placeholder_fields"] and time.monotonic() < deadline:
        page.wait_for_timeout(5_000)
        result = capture(page, offer, scope)
    result["assistant_region"]["load_wait_seconds"] = round(30 - max(0, deadline - time.monotonic()))
    if screenshot:
        region, _ = assistant_region(page)
        if region is not None:
            region.screenshot(path=str(SCREENSHOT_PATH), timeout=15_000)
        result["screenshot_path"] = str(SCREENSHOT_PATH)
    return result


def self_check() -> None:
    sample = """1688官方采购助手\n上架时间\n月成交\n-\n揽收率\n98%\n分销代发\n48h揽收率\n100%"""
    fields, _ = extract_top_fields(sample)
    assert fields["上架时间"]["status"] == "read_failed"
    assert fields["上架时间"]["raw_value"] is None
    assert fields["月成交"]["status"] == "placeholder"
    assert fields["揽收率"]["raw_value"] == "98%"
    assert "48h揽收率" not in str(fields["揽收率"]["raw_value"])
    assert same_raw_values(
        [{"status": "observed", "raw_value": "19", "observed_at": "t1"}],
        [{"status": "observed", "raw_value": "19", "observed_at": "t2"}],
    )
    print("visible-source parser self-check passed")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("a19", "five"), default="a19")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    targets = select_offers(args.scope)
    emit({"stage": "targets", "scope": args.scope, "offers": [
        {"offer_id": offer["offer_id"], "url": offer["url"], "shop": offer["shop_name"], "role": offer["group_role"]}
        for offer in targets
    ]})

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), channel="chrome", headless=False,
            ignore_default_args=["--no-sandbox", "--disable-extensions"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            results = []
            for index, offer in enumerate(targets):
                if index:
                    page.wait_for_timeout(5_000)
                result = observe(page, offer, args.scope)
                results.append(result)
                emit(result)
                if not result["offer_identity_verified"]:
                    emit({"stage": "stop", "reason": "offer_id_mismatch", "expected": offer["offer_id"],
                          "actual": result["page_offer_id"]})
                    return 2
                if result["assistant_region"].get("region_verified") is not True:
                    emit({"stage": "stop", "reason": "official_assistant_region_not_isolated"})
                    return 2
                if not result["extension_service_worker_loaded"]:
                    emit({"stage": "stop", "reason": "procurement_assistant_extension_not_running"})
                    return 2
                if args.scope == "a19":
                    page.wait_for_timeout(5_000)
                    page.reload(wait_until="domcontentloaded", timeout=45_000)
                    repeated = observe(page, offer, args.scope, screenshot=True)
                    repeated["repeat_validation"] = {
                        "repeats_observation_at": result["observed_at"],
                        "fields": {
                            name: {
                                "same_status": result["assistant_fields"][name]["status"] == repeated["assistant_fields"][name]["status"],
                                "same_raw_value": result["assistant_fields"][name]["raw_value"] == repeated["assistant_fields"][name]["raw_value"],
                            }
                            for name in TOP_FIELDS
                        },
                        "favorite_count_same": same_raw_values(
                            result["other_allowed_sources"]["收藏数"],
                            repeated["other_allowed_sources"]["收藏数"],
                        ),
                        "platform_tags_same": {
                            tag: result["other_allowed_sources"]["平台标签"][tag]["status"] == repeated["other_allowed_sources"]["平台标签"][tag]["status"]
                            for tag in TAGS
                        },
                        "scope": "same-session page reload; not cross-time validation",
                    }
                    emit(repeated)
                    if not repeated["offer_identity_verified"] or repeated["assistant_region"].get("region_verified") is not True:
                        emit({"stage": "stop", "reason": "A19_repeat_identity_or_source_mismatch"})
                        return 2
                    if not repeated["assistant_region"]["non_placeholder_fields"]:
                        emit({"stage": "stop", "reason": "A19_repeat_has_no_non_placeholder_value; five-Offer stage not run"})
                        return 2
            return 0
        except (PlaywrightTimeoutError, PlaywrightError) as error:
            emit({"stage": "failure", "failure_reason": error.__class__.__name__, "message": str(error)[:240]})
            return 3
        except RuntimeError as error:
            reason = str(error)
            emit({"stage": "failure", "failure_reason": reason})
            return 4 if "access_restricted" in reason else 2
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
