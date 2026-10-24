import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "daily_report.py"
spec = importlib.util.spec_from_file_location("daily_report", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class DailyReportTests(unittest.TestCase):
    def fixture(self, td):
        root=Path(td); src=root/"input.json"; out=root/"out"
        rows=[
            {"chat":"群A","sender":"同名","time":"2026-10-01T00:00:00+08:00","content":"窗口起点","source_file":"a"},
            {"chat":"群A","sender":"同名","time":"2026-10-01T12:00:00+08:00","content":"<msg><appmsg><title>新工具讨论</title><refermsg>引用的旧消息</refermsg></appmsg></msg>","source_file":"a"},
            {"chat":"群B","sender":"同名","time":"2026-10-01T12:30:00+08:00","content":"跨群不可引用","source_file":"b"},
            {"chat":"群A","sender":"乙","time":"2026-10-02T00:00:00+08:00","content":"右端排除","source_file":"a"},
            {"chat":"群A","sender":"丙","time":"2026-10-01T13:00:00+08:00","content":"实用链接 https://example.org/post","source_file":"a"},
            {"chat":"群A","sender":"丁","time":"2026-10-01T13:01:00+08:00","content":"技术链接 https://weixin.qq.com/s/secret","source_file":"a"},
            {"chat":"群A","sender":"戊","time":"2026-10-01T13:02:00+08:00","content":"[红包]","source_file":"a"},
            {"chat":"群A","sender":"长文","time":"2026-10-01T13:03:00+08:00","content":"长"*10000,"source_file":"a"},
            {"chat":"群A","sender":"丙","time":"2026-10-01T13:04:00+08:00","content":"再看一次 https://example.org/post","source_file":"a"},
            {"chat":"群A","sender":"图片发送者","time":"2026-10-01T13:05:00+08:00","content":"[图片]","source_file":"a"},
            {"chat":"群A","sender":"群A","time":"2026-10-01T13:06:00+08:00","content":"群公告内容","source_file":"a"},
            {"chat":"群A","sender":"wxid_member@chatroom","time":"2026-10-01T13:07:00+08:00","content":"系统提示","source_file":"a"},
            {"chat":"群A","sender":"己","time":"2026-10-01T13:08:00+08:00","content":"wxid_abc 0 1 前缀应去掉","source_file":"a"},
        ]
        src.write_text(json.dumps({"since":"old","until":"old","coverage":{"cap_reached":True,"read_limit":500,"live_database_read_ok":False,"collected_at":"2026-10-01T14:00:00+08:00","completeness":"unknown"},"messages":rows},ensure_ascii=False),encoding="utf-8")
        return src,out
    def test_prepare_filters_and_cleans(self):
        with tempfile.TemporaryDirectory() as td:
            src,out=self.fixture(td)
            subprocess.run([sys.executable,str(SCRIPT),"prepare",str(src),"--chat","群A","--since","2026-10-01","--until","2026-10-02","--timezone","Asia/Shanghai","--out",str(out)],check=True)
            m=json.loads((out/"material.json").read_text())
            self.assertEqual(m["message_count"],11)
            self.assertEqual(m["effective_evidence_count"],9)
            self.assertEqual(m["speaker_count"],7)
            self.assertEqual({x["chat"] for x in m["messages"]},{"群A"})
            content=" ".join(x["content"] for x in m["messages"])
            self.assertIn("新工具讨论",content); self.assertNotIn("引用的旧消息",content)
            self.assertNotIn("wxid_abc",content); self.assertIn("前缀应去掉",content)
            self.assertEqual(len(m["links"]),1); self.assertEqual(len(m["links"][0]["evidence_ids"]),2)
            self.assertNotIn("weixin.qq.com",content)
            self.assertIn("长"*10000,content)
            self.assertNotIn("群A",[s["name"] for s in m["speakers"]])
            self.assertNotIn("wxid_member@chatroom",[s["name"] for s in m["speakers"]])
            self.assertIn("不代表全量",m["coverage"]["statement"])
            self.assertEqual(m["coverage"]["input_coverage"]["cap_reached"],True)
            self.assertEqual(m["coverage"]["input_coverage"]["completeness"],"unknown")
            self.assertIn("读取上限：500",m["coverage"]["collection_note"])
    def test_empty_material_supported(self):
        with tempfile.TemporaryDirectory() as td:
            src,out=self.fixture(td)
            data=json.loads(src.read_text()); data["messages"]=[]; src.write_text(json.dumps(data))
            subprocess.run([sys.executable,str(SCRIPT),"prepare",str(src),"--chat","无消息群","--since","2026-10-01","--until","2026-10-02","--out",str(out)],check=True)
            m=json.loads((out/"material.json").read_text()); self.assertEqual(m["message_count"],0)
    def test_validate_evidence_and_derived_time(self):
        mat={"chat":"群A","messages":[{"evidence_id":"E1","chat":"群A","time":"2026-01-01T10:00:00+08:00"}]}
        ed={"lede":"具体导语","topics":[{"title":"具体项目出现新变化","start":"模型伪造","end":"x","evidence_ids":["E1"],"bullets":[{"text":"证据一","evidence_ids":["E1"]}],"insight":"需关注后续变化","boundary":"证据有限，仅一条消息"}],"angles":[],"attention":[]}
        errors=mod.validate_data(mat,ed)
        self.assertTrue(any("start 必须" in e for e in errors)); self.assertEqual(ed["topics"][0]["start"],"2026-01-01T10:00:00+08:00")
        mat["messages"][0]["chat"]="群B"; errors=mod.validate_data(mat,ed); self.assertTrue(any("不属于指定群" in e for e in errors))
    def test_render_escapes_user_html_and_javascript_url(self):
        mat={"chat":"<img src=x onerror=alert(1)>","since":"a","until":"b","timezone":"Asia/Shanghai","message_count":1,"speaker_count":1,"speakers":[],"links":[{"url":"javascript:alert(1)","evidence_id":"E1"}],"coverage":{"statement":"<script>alert(1)</script>","source":{"input_file":"x","input_mtime":"x"}}}
        ed={"lede":"<svg onload=alert(1)>","topics":[],"angles":[],"attention":[]}
        rendered=mod.render_html(mat,ed)
        self.assertNotIn("<script>alert",rendered); self.assertNotIn("<img src=x",rendered); self.assertNotIn('href="javascript:',rendered)
        self.assertIn("connect-src 'none'",rendered)
    def test_validate_rejects_vague_title_duplicate_insight_and_old_status(self):
        mat={"chat":"群A","message_count":1,"effective_evidence_count":1,"messages":[{"evidence_id":"E1","chat":"群A","time":"2026-01-01T10:00:00+08:00"}]}
        ed={"lede":"明确导语","topics":[{"title":"AI 产品/模型","evidence_ids":["E1"],"bullets":[{"text":"同一条具体事实","evidence_ids":["E1"]}],"insight":"同一条具体事实","boundary":"证据有限，仅一条"}],"angles":[],"attention":[{"text":"可能应该回复","status":"待核实","evidence_ids":["E1"]}],"links":[{"url":"https://example.org/a","title":"产品官方说明","evidence_ids":["E1"]}]}
        errors=mod.validate_data(mat,ed)
        self.assertTrue(any("过于宽泛" in e for e in errors))
        self.assertTrue(any("不得照抄" in e for e in errors))
        self.assertTrue(any("attention" in e and "status" in e for e in errors))
        self.assertEqual(mod.validate_data({**mat,"effective_evidence_count":0},{"lede":"暂无内容","topics":[],"angles":[],"attention":[],"links":[]}),[])
        self.assertTrue(any("topics_note" in e for e in mod.validate_data(mat,{"lede":"暂无","topics":[],"angles":[],"attention":[],"links":[]})))
    def test_editorial_links_status_and_accessible_html(self):
        mat={"chat":"群A","since":"2026-01-01T00:00:00+08:00","until":"2026-01-02T00:00:00+08:00","timezone":"Asia/Shanghai","message_count":1,"effective_evidence_count":1,"speaker_count":1,"speakers":[{"name":"甲","count":1}],"messages":[{"evidence_id":"E1","chat":"群A","sender":"甲","time":"2026-01-01T10:03:00+08:00","content":"依据"}],"links":[{"url":"https://example.org/guide","evidence_ids":["E1"]}],"coverage":{"statement":"覆盖说明","collection_note":"记录上限：200","source":{"input_file":"input.json","input_mtime":"mtime"}}}
        ed={"lede":"群内有一项需要观察的进展","topics":[{"title":"项目进展仍待进一步确认","start":"2026-01-01T10:03:00+08:00","end":"2026-01-01T10:03:00+08:00","evidence_ids":["E1"],"bullets":[{"text":"甲提出了一个具体观察。","evidence_ids":["E1"]}],"insight":"现有证据不足以形成最终结论","boundary":"证据有限，仅一条"}],"angles":[],"attention":[{"text":"尚无明确回复要求","status":"无需处理","evidence_ids":["E1"]}],"links":[{"url":"https://example.org/guide","title":"中文说明：查看项目操作指南","evidence_ids":["E1"]}]}
        errors=mod.validate_data(mat,ed); self.assertEqual(errors,[])
        page=mod.render_html(mat,ed)
        self.assertIn("10:03–10:03",page); self.assertIn("查看项目操作指南",page)
        self.assertNotIn('<caption>',page); self.assertEqual(page.count('<table>'),1)
        self.assertIn('E1 甲 10:03',page); self.assertNotIn('>[E1]</span>',page)
        markdown=mod.md_report(mat,ed)
        self.assertIn('<!-- evidence: E1 -->',markdown); self.assertNotIn('编辑判断：',markdown)
    def test_output_protection(self):
        with tempfile.TemporaryDirectory() as td:
            src,out=self.fixture(td); out.mkdir(); (out/"material.json").write_text("keep")
            with self.assertRaises(FileExistsError): mod.ensure_safe_paths(src,out)
    def test_existing_runner_directory_and_source_input_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); out=root/"out"; (out/"source").mkdir(parents=True)
            (out/"run_status.json").write_text("{}")
            src=out/"source"/"input.json"; src.write_text(json.dumps({"messages":[]}),encoding="utf-8")
            mod.ensure_safe_paths(src,out)
            self.assertTrue((out/"run_status.json").exists())
    def test_validate_and_render_cli_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            src,out=self.fixture(td)
            subprocess.run([sys.executable,str(SCRIPT),"prepare",str(src),"--chat","群A","--since","2026-10-01","--until","2026-10-02","--out",str(out)],check=True,capture_output=True)
            mat=json.loads((out/"material.json").read_text()); evidence=mat["messages"][0]["evidence_id"]
            ed={"lede":"群内围绕一个具体工具展开交流","topics":[{"title":"新工具讨论仍处于经验交换阶段","evidence_ids":[evidence],"bullets":[{"text":"成员分享了窗口内实际观察。","evidence_ids":[evidence]}],"insight":"现有材料不足以判断普遍效果","boundary":"证据有限，仅一条消息"}],"angles":[],"attention":[]}
            (out/"editorial.json").write_text(json.dumps(ed,ensure_ascii=False),encoding="utf-8")
            subprocess.run([sys.executable,str(SCRIPT),"validate","--out",str(out)],check=True,capture_output=True)
            subprocess.run([sys.executable,str(SCRIPT),"render","--out",str(out)],check=True,capture_output=True)
            self.assertTrue((out/"group_daily_report.html").is_file()); self.assertTrue((out/"group_daily_report.md").is_file())
            status=json.loads((out/"status.json").read_text()); self.assertEqual(status["render"],"complete")
    def test_safe_inline_bold_and_english_markdown(self):
        self.assertEqual(mod.inline_html('**张三** <script>bad</script>'), '<strong>张三</strong> &lt;script&gt;bad&lt;/script&gt;')
        self.assertEqual(mod.inline_md('**张三** reads'), '**张三** reads')
        self.assertEqual(mod.md_escape('张三\nreads'), '张三 reads')
        self.assertEqual(mod.md_url('https://example.org/a(b)'), 'https://example.org/a%28b%29')

    def test_current_xml_body_excludes_sender_metadata_and_keeps_article_url(self):
        body='<msg><appmsg><title>本条回应</title><refermsg><title>旧话</title></refermsg></appmsg><fromusername>account</fromusername><scene>0</scene></msg>'
        cleaned,links=mod.clean_content(body)
        self.assertEqual(cleaned,'本条回应')
        self.assertEqual(links,[])
        cleaned,links=mod.clean_content('文章 https://mp.weixin.qq.com/s/readable 技术 https://wxapp.tc.qq.com/stodownload')
        self.assertEqual(links,['https://mp.weixin.qq.com/s/readable'])

    def test_url_glued_to_chinese_text_is_split_and_kept_clickable(self):
        cleaned,links=mod.clean_content('基于开源仓库 https://github.com/Rion-Wu-tech/wechat-intelligence-hub只读微信 ，然后适配下')
        self.assertEqual(links,['https://github.com/Rion-Wu-tech/wechat-intelligence-hub'])
        self.assertIn('只读微信',cleaned)
        self.assertNotIn('hub只读',cleaned)

    def test_topic_times_cover_every_bullet_and_links_cannot_be_fabricated(self):
        mat={'chat':'群A','messages':[{'evidence_id':'E1','chat':'群A','time':'2026-01-01T10:00:00+08:00'},{'evidence_id':'E2','chat':'群A','time':'2026-01-01T11:00:00+08:00'}],'links':[]}
        ed={'lede':'具体导语','topics':[{'title':'具体项目出现新变化','evidence_ids':['E1'],'bullets':[{'text':'第一项观察','evidence_ids':['E1']},{'text':'后续出现纠正','evidence_ids':['E2']}],'insight':'先读后续修正再判断适用条件'}],'angles':[],'attention':[],'links':[{'url':'https://example.org/fake','title':'伪造的资料','evidence_ids':['E1']}]}
        errors=mod.validate_data(mat,ed)
        self.assertTrue(any('话题 evidence_ids' in e for e in errors))
        self.assertTrue(any('URL必须来自素材' in e for e in errors))

    def test_png_missing_reports_status(self):
        # A capability failure is an explicit state rather than silent success.
        result,note=mod.png_capture(Path("/nonexistent-directory"))
        self.assertIn(result,("missing-dependency","failed"))
        self.assertTrue(note)

if __name__=="__main__": unittest.main()
