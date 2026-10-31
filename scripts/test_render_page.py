#!/usr/bin/env python3
"""Run the renderer the way an agent does and read what lands on the page.

python scripts/test_render_page.py
RENDER_PAGE=<another render_page.py> checks that copy instead, to prove a test fails on old code.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

RENDERER = os.environ.get("RENDER_PAGE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_page.py")
# Built from parts so this file carries nothing that looks like a real secret itself.
FAKE_API_KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
FAKE_PASSWORD = "Sample-" + "Pass-2610"


class Project:
    def __init__(self, tracker, files=None):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        for rel, text in {"plans/TRACKER.md": tracker, **(files or {})}.items():
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def render(self, *extra):
        os.makedirs(os.path.join(self.root, "out"), exist_ok=True)
        self.output = os.path.join(self.root, "out", "page.html")
        return subprocess.run([sys.executable, RENDERER, "plans/TRACKER.md", self.output, *extra], cwd=self.root,
                              capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def page(self):
        with open(self.output, encoding="utf-8") as f:
            return f.read()

    def docs(self):
        found = re.search(r"const DOCS = (\[.*?\])\nconst SOURCE", self.page(), re.S)
        return [d["path"] for d in json.loads(found.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))]


def tracker_naming(*paths):
    lines = "\n".join(f"- `{p}`: a plan." for p in paths)
    return f"# Project\n\n## الآن\n- Building.\n\n## الخطط\n{lines}\n"


class Copying(unittest.TestCase):
    def test_a_named_plan_is_copied_and_the_plan_it_names_is_not(self):
        project = Project(tracker_naming("plans/a.md"), {
            "plans/a.md": "# A\nSee `plans/b.md` for the servers.\n",
            "plans/b.md": "# B\nThe servers' details.\n",
        })
        self.assertEqual(project.render().returncode, 0)
        self.assertEqual(project.docs(), ["plans/a.md"])
        self.assertNotIn("the servers&#x27; details", project.page().lower())

    def test_two_named_plans_link_to_each_other_in_either_order(self):
        project = Project(tracker_naming("plans/a.md", "plans/b.md"), {
            "plans/a.md": "# A\nSee `plans/b.md`.\n",
            "plans/b.md": "# B\nSee `plans/a.md`.\n",
        })
        project.render()
        self.assertEqual(project.docs(), ["plans/a.md", "plans/b.md"])
        self.assertIn('data-doc=\\"1\\"', project.page())
        self.assertIn('data-doc=\\"0\\"', project.page())

    def test_a_path_outside_the_project_stays_out(self):
        project = Project(tracker_naming("../outside.md"))
        with open(os.path.join(project.root, "..", "outside.md"), "w", encoding="utf-8") as f:
            f.write("# Outside\n")
        try:
            project.render()
            self.assertEqual(project.docs(), [])
        finally:
            os.remove(os.path.join(project.root, "..", "outside.md"))

    def test_a_file_too_large_for_a_phone_stays_out_and_is_reported(self):
        project = Project(tracker_naming("plans/big.md"), {"plans/big.md": "# Big\n" + "word " * 40000})
        result = project.render()
        self.assertEqual(project.docs(), [])
        self.assertIn("plans/big.md", result.stderr)

    def test_a_file_that_is_not_text_stays_out_without_a_crash(self):
        project = Project(tracker_naming("plans/odd.md"), {"plans/odd.md": b"\xff\xfe\x00broken"})
        result = project.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(project.docs(), [])


class Sensitive(unittest.TestCase):
    def refused(self, text):
        project = Project(tracker_naming("plans/x.md"), {"plans/x.md": f"# X\n{text}\n"})
        result = project.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        return project, result, project.docs() == []

    def test_each_kind_keeps_a_file_off_the_page(self):
        for text in [f"key {FAKE_API_KEY}", f"dev password `{FAKE_PASSWORD}`", f"كلمة المرور `{FAKE_PASSWORD}`",
                     f"password: {FAKE_PASSWORD}", "ssh -i ~/.ssh/server root@host", "server at 8.8.4.4",
                     "phone 01000000011", "phone +201000000123", "mail someone@gmail.com",
                     "-----BEGIN OPENSSH PRIVATE KEY-----", "https://user:hunter22@example.org/x"]:
            with self.subTest(text=text):
                self.assertTrue(self.refused(text)[2])

    def test_the_report_names_the_line_and_never_the_value(self):
        _, result, _ = self.refused(f"dev password `{FAKE_PASSWORD}`")
        self.assertIn("line 2", result.stderr)
        self.assertNotIn(FAKE_PASSWORD, result.stderr + result.stdout)

    def test_ordinary_prose_about_these_things_is_copied(self):
        for text in ["The token is signed by Laravel and expires with the lesson.",
                     "Config `services.livekit.{url,key,secret}` from the environment.",
                     "A password hashed twice never opens its account.", "`password => 'hashed'` is a cast.",
                     "password: <your password here>", "Bind to 127.0.0.1 or 10.0.0.5.", "Version 1.13.9 is fine.",
                     "Mail support@example.org.", "Costs $0.003 a minute, or 1,760 a month."]:
            with self.subTest(text=text):
                self.assertFalse(self.refused(text)[2])

    def test_allow_passes_one_file_a_person_has_read(self):
        project = Project(tracker_naming("plans/x.md", "plans/y.md"), {
            "plans/x.md": "# X\nserver at 8.8.4.4\n", "plans/y.md": "# Y\nserver at 8.8.4.4\n"})
        project.render("--allow", "plans/x.md")
        self.assertEqual(project.docs(), ["plans/x.md"])

    def test_a_secret_in_the_tracker_itself_writes_no_page(self):
        project = Project(f"# P\n\n## مفتوح\n- password: {FAKE_PASSWORD}\n")
        result = project.render()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(os.path.exists(project.output))
        self.assertNotIn(FAKE_PASSWORD, result.stderr)


class Page(unittest.TestCase):
    def test_a_line_holding_a_placeholder_name_cannot_break_the_page(self):
        project = Project(tracker_naming("plans/a.md") + "\n## مفتوح\n- Write __DOCS__ and __SECTIONS__ in the guide.\n",
                          {"plans/a.md": "# A\nText.\n"})
        project.render()
        page = project.page()
        self.assertIn("Write __DOCS__ and __SECTIONS__", page)
        self.assertEqual(page.count('"path": "plans/a.md"'), 1)

    def test_a_plan_cannot_close_the_script_or_open_a_tag(self):
        project = Project(tracker_naming("plans/a.md"), {"plans/a.md": "# A\n</script><img src=x onerror=alert(1)>\n<!-- <script>\n"})
        project.render()
        body = project.page().split("const DOCS = ", 1)[1].split("const SOURCE", 1)[0]
        self.assertNotIn("</script", body)
        self.assertNotIn("<!--", body)
        self.assertNotIn("<img", body)

    def test_item_text_is_escaped_and_only_web_links_become_links(self):
        project = Project("# P\n\n## مفتوح\n- <b>bold</b> [bad](javascript:alert(1)) [good](https://example.org)\n")
        project.render()
        page = project.page()
        self.assertIn("&lt;b&gt;", page)
        self.assertNotIn('href=\\"javascript', page)
        self.assertIn('href=\\"https://example.org\\"', page)

    def test_a_byte_order_mark_does_not_lose_the_title(self):
        project = Project("\ufeff# عنوان المشروع\n\n## الآن\n- Building.\n")
        project.render()
        self.assertIn("<title>عنوان المشروع</title>", project.page())

    def test_counts_read_as_arabic(self):
        for waiting, yours, expected in [(1, 0, "ينتظرك: قرار واحد."), (2, 1, "ينتظرك: قراران ومهمة واحدة."),
                                         (8, 2, "ينتظرك: 8 قرارات ومهمتان."), (11, 3, "ينتظرك: 11 قرارًا و3 مهام."),
                                         (0, 11, "ينتظرك: 11 مهمة."), (0, 0, "لا شيء ينتظرك الآن.")]:
            with self.subTest(waiting=waiting, yours=yours):
                wait = "".join(f"- q{i}\n" for i in range(waiting))
                mine = "".join(f"- t{i}\n" for i in range(yours))
                project = Project(f"# P\n\n## ينتظر قرارك\n{wait}\n## دورك أنت\n{mine}\n")
                project.render()
                self.assertIn(expected, project.page())

    def test_the_page_counts_items_with_the_same_grammar(self):
        project = Project("# P\n\n## مفتوح\n- one\n")
        project.render()
        self.assertIn("countItems(sec.items.length)", project.page())
        self.assertNotIn("sec.items.length + ' بند'", project.page())


class Ids(unittest.TestCase):
    def test_an_id_comes_from_the_section_and_the_text(self):
        # Ticks and notes are stored under these ids, so changing the recipe silently drops the owner's work.
        project = Project("# P\n\n## مفتوح\n- First item\n- ! Urgent item\n")
        result = subprocess.run([sys.executable, RENDERER, "--ids", "plans/TRACKER.md"], cwd=project.root,
                                capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = ["i" + hashlib.sha1(("مفتوح" + text).encode()).hexdigest()[:10] for text in ["First item", "Urgent item"]]
        self.assertEqual([line.split(" ", 1)[0] for line in result.stdout.splitlines()], expected)


if __name__ == "__main__":
    unittest.main()
