"""Pure structural checks for the stable reference presentation."""
from html.parser import HTMLParser
import re


class Outline(HTMLParser):
    def __init__(self):
        super().__init__()
        self.heading = None
        self.headings = []
        self.current = []
        self.tables = 0
        self.table_headers = []
        self.in_th = False
        self.th = []
        self.quotes = 0
        self.articles = 0
        self.anchors = []
        self.anchor = None
        self.anchor_text = []
        self.visible = []
        self.in_body = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'body': self.in_body = True
        if tag in ('h1', 'h2'):
            self.heading = tag
            self.current = []
        if tag == 'br' and self.heading: self.current.append('\n')
        if tag == 'table': self.tables += 1
        if tag == 'th': self.in_th = True; self.th = []
        if tag == 'blockquote': self.quotes += 1
        if tag == 'article' and 'topic' in attrs.get('class', '').split(): self.articles += 1
        if tag == 'a': self.anchor = attrs.get('href', ''); self.anchor_text = []

    def handle_data(self, data):
        if self.heading: self.current.append(data)
        if self.in_th: self.th.append(data)
        if self.anchor is not None: self.anchor_text.append(data)
        if self.in_body and self.anchor is None and not self.heading: self.visible.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading:
            self.headings.append((tag, ''.join(self.current)))
            self.heading = None
        if tag == 'th':
            self.table_headers.append(''.join(self.th))
            self.in_th = False
        if tag == 'a' and self.anchor is not None:
            self.anchors.append((self.anchor, ''.join(self.anchor_text)))
            self.anchor = None
        if tag == 'body': self.in_body = False


def check_html(page, material, editorial, link_count):
    parser = Outline()
    parser.feed(page)
    errors = []
    if ('h1', material['chat'] + '\n今日内容总结') not in parser.headings:
        errors.append('主标题必须是群名换行今日内容总结')
    expected = (['活跃度'] if material.get('speakers') else []) + ['话题', '可做选题的线索', '需要你留意的', '今日链接']
    if [text for tag, text in parser.headings if tag == 'h2'] != expected:
        errors.append('栏目名称或顺序偏离固定模板')
    topics = len(editorial.get('topics', []))
    if parser.articles != topics or parser.quotes != topics:
        errors.append('每个话题必须对应一张卡和一段总结')
    if parser.tables != bool(editorial.get('attention')):
        errors.append('只允许非空提醒表，不显示额外发言统计表')
    if parser.tables and parser.table_headers != ['时间', '事项', '状态']:
        errors.append('提醒表头必须是时间/事项/状态')
    if len(parser.anchors) != link_count or any(href != label for href, label in parser.anchors):
        errors.append('今日链接必须逐项显示实际URL，不能只显示中文标题或域名')
    stats = re.findall(r'<div class="stat"><b>(\d+)</b><span>([^<]+)</span></div>', page)
    wanted = [(str(material['message_count']), '条消息'), (str(material['speaker_count']), '人发言'), (str(topics), '个话题'), (str(link_count), '个链接')]
    if stats != wanted: errors.append('四格数字/标签与实际话题和链接不一致')
    if page.index('<p class="meta">') > page.index('<h1>'):
        errors.append('日期必须在主标题上方')
    visible = ''.join(parser.visible)
    if '总结 · 编辑判断' in visible or '真人发言' in visible or '真实发言统计' in visible:
        errors.append('页面含旧版审计标签或额外发言统计')
    if editorial.get('format_version') == 2 and ('**' in visible or '==' in visible):
        errors.append('页面有未渲染的加粗/高亮标记')
    return errors
