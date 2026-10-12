"""Offline regressions; no browser, profile or platform access."""
import unittest
from unittest.mock import Mock, patch

import probe


class ProbeTests(unittest.TestCase):
    def test_display_strings(self):
        # 20+ and <10 were observed in historical sales responses, not this panel.
        for text in ('月成交 20+\n月代销 <10', '月成交：20+ 月代销：<10',
                     '月成交\n20+\n月代销\n<10'):
            fields, _ = probe.extract_top_fields(text)
            self.assertEqual(fields['月成交']['raw_value'], '20+')
            self.assertEqual(fields['月代销']['raw_value'], '<10')
        fields, _ = probe.extract_top_fields('揽收率 98%\n分销代发\n48h揽收率 100%')
        self.assertEqual(fields['揽收率']['raw_value'], '98%')
        fields, _ = probe.extract_top_fields('月成交\n加载中\n月代销 -')
        self.assertEqual(fields['月成交']['status'], 'loading')
        fields, _ = probe.extract_top_fields('年成交笔数 1300+\n评论数 0\n上架时间：2026-09-01')
        self.assertEqual(fields['年成交笔数']['raw_value'], '1300+')
        self.assertEqual(fields['评论数']['raw_value'], '0')
        self.assertEqual(fields['上架时间']['raw_value'], '2026-09-01')
        fields, _ = probe.extract_top_fields('月成交\n月代销\n-')
        self.assertEqual(fields['月成交']['status'], 'read_failed')

    def test_repeat_does_not_navigate(self):
        page = Mock()
        result = {'assistant_region': {'header_visible': False}}
        with patch.object(probe, 'page_gate', return_value=None), patch.object(probe, 'capture', return_value=result):
            probe.observe(page, {'url': 'unused'}, 'a19', navigate=False)
        page.goto.assert_not_called()
        page.reload.assert_not_called()
        with patch.object(probe, 'page_gate', return_value=None), patch.object(probe, 'capture', return_value=result):
            probe.observe(page, {'url': 'unused'}, 'a19')
        page.goto.assert_called_once()

    def test_supplied_offer_requires_exact_detail_url(self):
        offer = probe.supplied_offer('https://detail.1688.com/offer/1085110305278.html')
        self.assertEqual(offer['offer_id'], '1085110305278')
        self.assertEqual(offer['group_role'], 'user_supplied')
        for url in (
            'http://detail.1688.com/offer/1085110305278.html',
            'https://evil.example/offer/1085110305278.html',
            'https://detail.1688.com/offer/1085110305278.html?token=x',
            'https://detail.1688.com/offer/not-a-number.html',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.supplied_offer(url)

    def test_request_failure_is_not_normal_placeholder(self):
        self.assertEqual(probe.data_state(None, [{'http_status': 403}]), 'data_request_failed')
        self.assertEqual(probe.data_state(None, [{'transport_failed': True}]), 'data_request_failed')
        self.assertEqual(probe.data_state(None, [{'http_status': 200}]), 'unknown')
        self.assertEqual(probe.data_state('verification required', []), 'verification required')

    def test_embedded_verification(self):
        page = Mock(url='https://detail.1688.com/offer/1079985611201.html')
        page.title.return_value = '商品详情'
        frame = Mock()
        frame.is_visible.return_value = True
        frame.get_attribute.return_value = 'https://example.test/captcha'
        page.locator.return_value.all.return_value = [frame]
        self.assertEqual(probe.page_gate(page), 'verification required')
        frame.is_visible.return_value = False
        marker = Mock()
        marker.is_visible.return_value = True
        page.get_by_text.return_value.all.return_value = [marker]
        self.assertEqual(probe.page_gate(page), 'verification required')
        marker.is_visible.return_value = False
        self.assertIsNone(probe.page_gate(page))

    def test_user_verification_waits_until_cleared(self):
        page = Mock()
        with patch.object(probe, 'page_gate', side_effect=('verification required', None)), patch.object(probe, 'emit'):
            probe.wait_for_user_verification(page, '1085110305278')
        page.wait_for_timeout.assert_called_once_with(2_000)


if __name__ == '__main__':
    unittest.main()
