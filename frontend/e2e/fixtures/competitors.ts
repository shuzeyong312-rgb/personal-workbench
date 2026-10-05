import type { Competitor } from "../../src/App";

export function makeCompetitor(index: number, overrides: Partial<Competitor> = {}): Competitor {
  return { id: index, platform: "1688", offer_id: `offer-${String(index).padStart(3, "0")}`, url: `https://detail.1688.com/offer/${index}.html`, group_id: null, group_role: "competitor", ownership: "competitor", title: index === 1 ? "搜索目标竞品 01" : `固定竞品 ${String(index).padStart(2, "0")}`, shop_name: `测试店铺 ${index}`, main_image_url: null, status: "active", is_active: index % 7 !== 0, created_at: "2026-09-01T00:00:00Z", last_collected_at: null, latest_snapshot: null, latest_change: null, ...overrides };
}

export function makeCompetitors(count: 10 | 11 | 23 = 23): Competitor[] { return Array.from({ length: count }, (_, index) => makeCompetitor(index + 1)); }
export const competitors23 = makeCompetitors(23);
