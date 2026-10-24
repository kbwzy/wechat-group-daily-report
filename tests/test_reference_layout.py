import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reference_daily', ROOT / 'scripts/daily_report.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def fixture():
    messages = [
        {'evidence_id': 'A', 'chat': '测试群', 'sender': '甲', 'time': '2026-10-23T09:01:00+08:00', 'content': '先把剪辑流程做简单 https://example.org/guide', 'reply_to': ''},
        {'evidence_id': 'B', 'chat': '测试群', 'sender': '乙', 'time': '2026-10-23T09:03:00+08:00', 'content': '少做不需要的分析功能', 'reply_to': '读者'},
    ]
    mat = {'chat': '测试群', 'since': '2026-10-23T00:00:00+08:00', 'until': '2026-10-23T18:00:00+08:00', 'timezone': 'Asia/Shanghai',
           'message_count': 2, 'effective_evidence_count': 2, 'speaker_count': 2, 'speakers': [{'name': '甲', 'count': 1}, {'name': '乙', 'count': 1}],
           'audience': {'owner_aliases': ['读者']}, 'messages': messages, 'links': [{'url': 'https://example.org/guide', 'evidence_ids': ['A']}], 'coverage': {}}
    ed = {'format_version': 2, 'lede': '今天最有意思的，是大家先给需求减了减负。',
          'topics': [{'title': '先把成片做出来，复杂分析晚点再加', 'tone': 'insight', 'kind': 'discussion', 'evidence_ids': ['A', 'B'],
                      'bullets': [{'text': '**甲**提醒，==先把剪辑做简单==，别一开始就堆功能。', 'evidence_ids': ['A']},
                                  {'text': '**乙**补充，少做用不到的分析，先验证成片效果。', 'evidence_ids': ['B']}],
                      'insight': '给需求减减负，比继续给方案加装备管用；先让一条片子顺利出门，再讨论更大的系统。'}],
          'angles': [{'title': '别给小需求配大装备', 'text': '**甲**这次的澄清，适合写成一次需求收窄练习。', 'evidence_ids': ['A', 'B']}],
          'attention': [{'scope': 'direct', 'anchor_id': 'B', 'text': '**乙**已经接住你的问题，给出了简化方向。', 'status': '无需处理', 'evidence_ids': ['B']}],
          'links': [{'url': 'https://example.org/guide', 'title': '剪辑流程参考', 'evidence_ids': ['A']}]}
    return mat, ed


class ReferenceLayoutTests(unittest.TestCase):
    def test_fixed_masthead_outline_chips_quotes_and_no_statistics_table(self):
        mat, ed = fixture()
        self.assertEqual(daily.validate_data(mat, ed, strict=True), [])
        page = daily.render_html(mat, ed)
        self.assertEqual(daily.local_module('layout_check').check_html(page, mat, ed, 1), [])
        self.assertIn('<h1>测试群<br>今日内容总结</h1>', page)
        self.assertLess(page.index('2026-10-23（周五）'), page.index('<h1>'))
        self.assertIn('<h3><span class="tag">', page)
        self.assertIn('<blockquote><strong>总结：</strong>', page)
        self.assertIn('<span class="hl">先把剪辑做简单</span>', page)
        self.assertNotIn('<caption>', page)
        self.assertNotIn('总结 · 编辑判断', page)
        self.assertNotIn('class="pill"', page)

    def test_links_show_time_sender_chinese_description_and_actual_url(self):
        mat, ed = fixture()
        daily.validate_data(mat, ed)
        page = daily.render_html(mat, ed)
        self.assertIn('09:01 <strong>甲</strong>｜剪辑流程参考｜<a', page)
        self.assertIn('>https://example.org/guide</a>', page)

    def test_personal_reminder_requires_real_direction_and_correct_anchor(self):
        mat, ed = fixture()
        self.assertEqual(daily.validate_data(mat, ed, strict=True), [])
        ed['attention'][0]['evidence_ids'] = ['A']
        ed['attention'][0]['anchor_id'] = 'A'
        self.assertTrue(any('不能标direct' in e for e in daily.validate_data(mat, ed, strict=True)))
        ed['attention'][0]['scope'] = 'reference'
        ed['attention'][0]['status'] = '待回应'
        self.assertTrue(any('不能标待回应' in e for e in daily.validate_data(mat, ed, strict=True)))

    def test_empty_reminders_have_explanation_but_no_empty_table(self):
        mat, ed = fixture()
        ed['attention'] = []
        daily.validate_data(mat, ed)
        page = daily.render_html(mat, ed)
        self.assertNotIn('<table', page)
        self.assertIn('未识别到需要你跟进', page)
        self.assertEqual(daily.local_module('layout_check').check_html(page, mat, ed, 1), [])

    def test_strict_style_checks_density_highlights_and_version(self):
        mat, ed = fixture()
        ed['format_version'] = 1
        self.assertTrue(any('format_version=2' in e for e in daily.validate_data(mat, ed, strict=True)))
        ed['format_version'] = 2
        ed['topics'][0]['bullets'][0]['text'] = '没有姓名加粗，也没有重点。'
        ed['topics'][0]['bullets'][1]['text'] = 'x' * 116
        errors = daily.validate_data(mat, ed, strict=True)
        self.assertTrue(any('至少加粗' in e for e in errors))
        self.assertTrue(any('==高亮==' in e for e in errors))
        self.assertTrue(any('115' in e for e in errors))

    def test_nested_markup_and_missing_links_are_rejected(self):
        mat, ed = fixture()
        ed['topics'][0]['bullets'][0]['text'] = '**甲说==重点==**'
        ed['links'] = []
        errors = daily.validate_data(mat, ed, strict=True)
        self.assertTrue(any('不要嵌套' in e for e in errors))
        self.assertTrue(any('不能静默漏项' in e for e in errors))

    def test_negated_safety_warning_is_not_an_unconditional_guarantee(self):
        mat, ed = fixture()
        ed['topics'][0]['insight'] = '别把一次能访问当成长期安全保证，先问清楚风险来自哪里，再决定是否采用。'
        self.assertEqual(daily.validate_data(mat, ed, strict=True), [])
        ed['topics'][0]['insight'] = '采用这个方法就一定安全，任何时候都不会发生封号问题。'
        self.assertTrue(any('无条件保证' in e for e in daily.validate_data(mat, ed, strict=True)))

    def test_xml_reply_name_is_metadata_not_a_second_message(self):
        raw = '<msg><appmsg><title>已经回答</title><refermsg><displayname>读者</displayname><content>旧消息</content></refermsg></appmsg></msg>'
        self.assertEqual(daily.reply_sender(raw), '读者')
        self.assertEqual(daily.clean_content(raw)[0], '已经回答')

    def test_layout_guard_catches_changed_heading_and_hidden_urls(self):
        mat, ed = fixture()
        daily.validate_data(mat, ed)
        page = daily.render_html(mat, ed)
        changed = page.replace('>今日链接</h2>', '>资源推荐</h2>')
        self.assertTrue(any('栏目名称' in e for e in daily.local_module('layout_check').check_html(changed, mat, ed, 1)))
        changed = page.replace('>https://example.org/guide</a>', '>点击这里</a>')
        self.assertTrue(any('实际URL' in e for e in daily.local_module('layout_check').check_html(changed, mat, ed, 1)))

    def test_render_is_deterministic_and_markdown_uses_same_contract(self):
        mat, ed = fixture()
        daily.validate_data(mat, ed)
        self.assertEqual(daily.render_html(mat, ed), daily.render_html(copy.deepcopy(mat), copy.deepcopy(ed)))
        text = daily.md_report(mat, ed)
        self.assertTrue(text.startswith('[meta]2026-10-23（周五）'))
        self.assertIn('# 测试群<br>今日内容总结', text)
        self.assertIn('> **总结：**', text)
        self.assertIn('| 时间 | 事项 | 状态 |', text)
        self.assertNotIn('编辑判断：', text)


if __name__ == '__main__':
    unittest.main()
