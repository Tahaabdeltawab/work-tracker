#!/usr/bin/env python3
"""Render a TRACKER.md into the page the owner reads on a phone.

The markdown stays the only source; never edit the page by hand. Understands one
# title, ## sections, ### groups (each folds on its own), an italic note line,
**bold**, `code`, [text](url), and:
  - text          an item
  - ! text        an urgent item (red rank)
    - detail      a detail line under the item above; the item then folds open
  | a | b |       a table, shown at the end of its group

A plan file named as `plans/x.md`, [text](plans/x.md) or plain plans/x.md is copied
into the page and opens in a dialog, because a phone cannot reach the repository.
Under الخطط any .md path inside the project counts; elsewhere only those under plans/.

Only files the tracker itself names are copied. A path inside a copied file links to
another copied file and pulls nothing new in, so naming one plan cannot carry a second
one onto the page unseen. A file that looks like it holds a secret or a person's details,
or is too large for a phone, stays out and is reported by line and kind, never by value.
A tracker that trips the same check writes no page at all. --allow <path> passes one file
after a person has read it.

The owner's ticks live in the page's `db` capability, collection `checks`, under
the ids that --ids prints. An id comes from the item's section and text, so
rewording an item drops its tick. The owner's notes live beside them in collection `notes`,
under the same ids, as {text, at}.

Two controls float at the foot of the page: «حدد وأرسل» sends the picked items, and
«أرسل كل الملاحظات» sends every item that has a note, to the owner's Claude session through the `room`
capability, as {label, action, source, items: [{id, section, text, details, note}]}, with
`note` only on an item that has one. Publish
with capabilities {db: {}, room: {}}; without `room` the control stays hidden.

Usage: render_page.py <tracker.md> <output.html> [--allow <path>]...
       render_page.py --ids <tracker.md>
"""
import argparse
import hashlib
import html
import ipaddress
import json
import os
import re
import sys

STATUS_BY_SECTION = {
    "الآن": "now",
    "ينتظر قرارك": "wait",
    "دورك أنت": "you",
    "مفتوح": "todo",
    "قرارات سارية": "rule",
    "الخطط": "plan",
    "الأرشيف": "plan",
}
OPEN_BY_DEFAULT = {"ينتظر قرارك", "دورك أنت"}
PLANS_SECTION = "الخطط"
DOC_ROOT = None
DOCS = {}
REFUSED = {}
ALLOWED = set()
READING_DOCS = False
MAX_DOC_BYTES = 128 * 1024
MAX_ALL_DOCS_BYTES = 1024 * 1024

# Each is (what to call it, pattern). A match keeps a file off the page, so these lean towards catching too much.
SENSITIVE = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("API key", re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}"
                           r"|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}"
                           r"|[rs]k_live_[A-Za-z0-9]{16,})")),
    ("signed token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("password in a URL", re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.I)),
    ("SSH key path", re.compile(r"(?:^|[\s`\"'~/\\])\.ssh[/\\]")),
    ("phone number", re.compile(r"(?<![\w.+/-])(?:\+\d{10,15}|0\d{9,10})(?![\w.-])")),
    ("personal email", re.compile(r"[\w.+-]+@(?:gmail|googlemail|yahoo|hotmail|outlook|icloud|proton(?:mail)?)\.[a-z.]+", re.I)),
]
SECRET_WORD = r"(?:password|passwd|pwd|passphrase|secret|api[_ -]?key|كلمة (?:ال)?مرور|كلمة (?:ال)?سر)"
ASSIGNED_SECRET = re.compile(
    rf"{SECRET_WORD}\s*(?:=>|[:=])?\s*[`\"'](?P<quoted>[^`\"'\s]{{4,}})[`\"']"
    rf"|{SECRET_WORD}\s*[:=]\s*(?P<bare>[^\s`\"']{{4,}})"
    r"|[a-z_]*token\s*[:=]\s*[`\"']?(?P<token>[^\s`\"']{16,})",
    re.I,
)
PLACEHOLDER = re.compile(r"^(?:<.*|\$\{?\w+\}?|\{\{.*\}\}|[*x.…-]+|null|none|true|false|hashed|required|your[_-].*|example.*|changeme)[,;.)]*$", re.I)
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
DECISION_FORMS = ("قرار واحد", "قراران", "قرارات", "قرارًا", "قرار")
TASK_FORMS = ("مهمة واحدة", "مهمتان", "مهام", "مهمة", "مهمة")

PAGE = r"""<title>__TITLE__</title>
<!-- work-tracker: rendered from the project's TRACKER.md by the skill's scripts/render_page.py. Edit the file, not this page. -->
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600&family=Noto+Kufi+Arabic:wght@600;700&display=swap">
<style>
/* One narrow reading column: what is running now, then what waits on the owner, then the rest. Every item folds and ticks. */
:root {
  --bg: #f6f7f5; --surface: #ffffff; --ink: #1d2a28; --muted: #5f6d6a; --line: #dfe4e1; --accent: #0f6b5c;
  --now-bg: #e3f1ec; --now-fg: #0b5446;
  --wait-bg: #fdf0d9; --wait-fg: #8a5300;
  --you-bg: #f3e6f7; --you-fg: #6d2d84;
  --todo-bg: #eceeed; --todo-fg: #4c5755;
  --done-bg: #e6eefb; --done-fg: #234f9a;
  --hot: #b4361f; --drop-fg: #8b9491;
  --display: "Noto Kufi Arabic", "IBM Plex Sans Arabic", Tahoma, sans-serif;
  --body: "IBM Plex Sans Arabic", "Segoe UI", Tahoma, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121816; --surface: #1a2220; --ink: #e5ece9; --muted: #9aa8a4; --line: #2b3633; --accent: #5cc5ae;
  --now-bg: #173a32; --now-fg: #8fe0cb; --wait-bg: #3b2c12; --wait-fg: #f2c27a;
  --you-bg: #33203b; --you-fg: #dcaaef; --todo-bg: #252e2c; --todo-fg: #b3bfbc;
  --done-bg: #1c2a42; --done-fg: #9dbcf2; --hot: #ff8a70; --drop-fg: #6d7975; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121816; --surface: #1a2220; --ink: #e5ece9; --muted: #9aa8a4; --line: #2b3633; --accent: #5cc5ae;
  --now-bg: #173a32; --now-fg: #8fe0cb; --wait-bg: #3b2c12; --wait-fg: #f2c27a;
  --you-bg: #33203b; --you-fg: #dcaaef; --todo-bg: #252e2c; --todo-fg: #b3bfbc;
  --done-bg: #1c2a42; --done-fg: #9dbcf2; --hot: #ff8a70; --drop-fg: #6d7975; color-scheme: dark }

body { background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 15px; line-height: 1.7;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 20px 48px; }
.wrap { max-width: 780px; margin: 0 auto; display: grid; gap: 26px; }
header { display: grid; gap: 6px; }
h1 { font-family: var(--display); font-size: 1.55rem; margin: 0; text-wrap: balance; }
.stamp, .sync { color: var(--muted); font-size: .85rem; margin: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }

.now { background: var(--surface); border: 1px solid var(--line); border-inline-start: 4px solid var(--accent); border-radius: 10px; padding: 14px 16px; display: grid; gap: 4px; min-width: 0; }
.now .label { font-family: var(--display); font-size: .8rem; color: var(--accent); }
.now p { margin: 0; overflow-wrap: anywhere; }
.now .next { color: var(--muted); font-size: .9rem; }

details.sec > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; gap: 8px; padding: 4px 0; }
details.sec > summary::-webkit-details-marker { display: none; }
details.sec > summary h2 { font-family: var(--display); font-size: 1.05rem; margin: 0; }
details.sec > summary .count { font-size: .8rem; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
details.sec > summary::before { content: "▸"; color: var(--muted); font-size: .8rem; transition: transform .15s; display: inline-block; transform: scaleX(-1); }
details.sec[open] > summary::before { transform: rotate(90deg); }
.sec-wrap { display: grid; gap: 18px; min-width: 0; }
.list { margin-top: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; min-width: 0; }

.item { border-top: 1px solid var(--line); min-width: 0; }
.item:first-child { border-top: 0; }
.row { list-style: none; display: grid; grid-template-columns: auto auto 1fr auto auto; gap: 10px; align-items: center; padding: 10px 14px; }
details.item > summary { cursor: pointer; }
details.item > summary::-webkit-details-marker { display: none; }
details.item > summary:focus-visible, details.sec > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
.rank { font-variant-numeric: tabular-nums; color: var(--muted); font-size: .8rem; min-width: 1.4em; text-align: center; }
.rank.hot { color: var(--hot); font-weight: 600; }
input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent); margin: 0; cursor: pointer; }
.t { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.rule .t { font-weight: 400; }
details.item > summary .t::after { content: " ⌄"; color: var(--muted); font-weight: 400; }
.item.checked .t { color: var(--drop-fg); text-decoration: line-through; }
.note-btn { grid-column: 5; background: none; border: 0; padding: 0; width: 36px; height: 36px; color: var(--muted); font-size: 1.05rem; border-radius: 8px; }
.note-btn:focus-visible, .note-in:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.note { padding: 0 14px 12px; padding-inline-start: 62px; display: grid; gap: 2px; min-width: 0; }
.note[hidden] { display: none; }
.note-in { scroll-margin-bottom: 110px; width: 100%; box-sizing: border-box; min-height: 40px; resize: none; overflow: hidden; field-sizing: content; font: inherit; font-size: 16px; line-height: 1.5; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; }
.note-in::placeholder { color: var(--muted); }
.note-said { color: var(--muted); font-size: .78rem; min-height: 1.2em; }
.now .note { padding: 4px 0 6px; }
.now-line .note-btn { flex: none; margin-inline-start: auto; align-self: center; }
.body { padding: 0 14px 12px 14px; padding-inline-start: 62px; color: var(--muted); font-size: .9rem; }
.body ul { margin: 0; padding-inline-start: 18px; }
.body li { margin: 2px 0; overflow-wrap: anywhere; }
.body strong, .t strong { color: var(--ink); }
a { color: var(--accent); }
code { font: .85em Consolas, "Courier New", monospace; direction: ltr; unicode-bidi: isolate; }
.pill { font-size: .75rem; font-weight: 600; padding: 2px 10px; border-radius: 999px; white-space: nowrap; }
.s-now { background: var(--now-bg); color: var(--now-fg); }
.s-wait { background: var(--wait-bg); color: var(--wait-fg); }
.s-you { background: var(--you-bg); color: var(--you-fg); }
.s-todo { background: var(--todo-bg); color: var(--todo-fg); }
.s-done { background: var(--done-bg); color: var(--done-fg); }
.tables { padding: 10px 14px; border-top: 1px solid var(--line); display: grid; gap: 14px; }
.list > .tables:first-child { border-top: 0; }
.tbl { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; font-variant-numeric: tabular-nums; }
th, td { text-align: start; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td:first-child { white-space: normal; min-width: 9em; }
th { color: var(--muted); font-weight: 600; }
footer { color: var(--muted); font-size: .82rem; }
button { font: inherit; cursor: pointer; }
.btn { border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 8px; padding: 6px 12px; font-size: .88rem; font-weight: 600; min-height: 36px; }
.btn.main { background: var(--accent); border-color: var(--accent); color: var(--surface); }
.btn:focus-visible, .doclink:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.btn:disabled { opacity: .5; cursor: default; }
.tools .btn { flex: 1 1 auto; }
.tools .said { flex: 1 0 100%; color: var(--muted); font-size: .85rem; margin: 0; }
.tools .said:empty { display: none; }
.wrap.docked { padding-bottom: 96px; }
.selecting .row { cursor: pointer; }
.now-line { display: flex; gap: 10px; align-items: baseline; }
.now-line input { flex: none; align-self: center; }
.bar { position: fixed; z-index: 5; inset-inline: max(16px, env(safe-area-inset-left, 0px)); bottom: max(12px, env(safe-area-inset-bottom, 0px)); max-width: 780px; margin-inline: auto;
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; box-shadow: 0 6px 24px rgb(0 0 0 / .18); }
.bar[hidden] { display: none; }
.bar .count { flex: 1 1 120px; font-weight: 600; font-size: .9rem; font-variant-numeric: tabular-nums; }
.doclink { background: none; border: 0; padding: 0; color: var(--accent); text-decoration: underline; text-underline-offset: 3px; font-weight: inherit; text-align: start; overflow-wrap: anywhere; }
.doclink code { color: inherit; }
dialog.doc { width: min(780px, calc(100vw - 24px)); max-height: calc(100dvh - 24px); padding: 0; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); color: var(--ink); overflow: hidden; }
dialog.doc[open] { display: flex; flex-direction: column; }
dialog.doc::backdrop { background: rgb(0 0 0 / .5); }
.doc-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
.doc-head h2 { flex: 1; min-width: 0; margin: 0; font-family: var(--display); font-size: 1.02rem; overflow-wrap: anywhere; }
.doc-body { padding: 4px 16px 18px; overflow-y: auto; font-size: .94rem; }
.doc-body h3 { font-family: var(--display); font-size: 1rem; margin: 20px 0 6px; }
.doc-body h4, .doc-body h5 { font-size: .94rem; margin: 14px 0 4px; }
.doc-body p { margin: 8px 0; overflow-wrap: anywhere; }
.doc-body .note { color: var(--muted); font-size: .86rem; }
.doc-body ul, .doc-body ol { margin: 6px 0; padding-inline-start: 20px; }
.doc-body li { margin: 3px 0; overflow-wrap: anywhere; }
.doc-body hr { border: 0; border-top: 1px solid var(--line); margin: 14px 0; }
.doc-body pre { background: var(--bg); border-radius: 8px; padding: 10px; overflow-x: auto; direction: ltr; text-align: left; }
.doc-body .tbl { margin: 8px 0; }
.doc-body th, .doc-body td { white-space: normal; min-width: 5em; vertical-align: top; overflow-wrap: anywhere; }
@media (max-width: 480px) {
  .row { grid-template-columns: auto auto 1fr auto; }
  .row .pill { grid-column: 3; grid-row: 2; justify-self: start; }
  .note-btn { grid-column: 4; grid-row: 1; }
  .body, .note { padding-inline-start: 14px; }
}
/* The on-screen keyboard would lift the dock over the line being typed; tapping away brings it back. */
@media (pointer: coarse) { .wrap:has(.note-in:focus) .bar { display: none; } }
@media (prefers-reduced-motion: reduce) { details.sec > summary::before { transition: none; } }
</style>

<div class="wrap" dir="rtl" lang="ar">
  <header>
    <h1>__TITLE__</h1>
    <p class="stamp">__NOTE__</p>
    <div class="legend">
      <span class="pill s-now">جارٍ</span>
      <span class="pill s-wait">ينتظر قرارك</span>
      <span class="pill s-you">دورك أنت</span>
      <span class="pill s-todo">لم يبدأ</span>
      <span class="pill s-done">تم</span>
    </div>
    <p class="sync" id="sync">الرقم بجانب كل بند ترتيبه في الأولوية، والأحمر عاجل. اضغط البند ذا السهم ليفتح، وعلّم المربع حين ينتهي. اكتب قرارك في خانته، أو ملاحظتك بزر ✎، فتُحفظ مع البند وتصلني معه حين ترسله.</p>
  </header>

  <div class="now">
    <span class="label">نعمل الآن على</span>
    <div id="nowText"></div>
    <p class="next" id="nowNext"></p>
  </div>

  <div class="sec-wrap" id="sections"></div>

  <footer>تُولَّد هذه الصفحة من <code>__SOURCE__</code> بعد كل تحديث. ما ينتهي يُحذف من الملف، وما تعلّمه أنت أقرؤه أنا.</footer>

  <div class="bar tools" id="tools" hidden>
    <button type="button" class="btn" id="pickToggle">حدد بنودًا وأرسلها لي</button>
    <button type="button" class="btn main" id="sendNoted"></button>
    <p class="said" id="said" role="status"></p>
  </div>

  <div class="bar" id="bar" hidden>
    <span class="count" id="barCount" role="status"></span>
    <button type="button" class="btn main" id="sendNow">نفّذها الآن</button>
    <button type="button" class="btn" id="sendStage">ضعها في رسالتي</button>
    <button type="button" class="btn" id="pickCancel">إلغاء</button>
  </div>

  <dialog class="doc" id="doc" aria-labelledby="docTitle">
    <div class="doc-head">
      <h2 id="docTitle"></h2>
      <button type="button" class="btn" id="docClose">إغلاق</button>
    </div>
    <div class="doc-body" id="docBody"></div>
  </dialog>
</div>

<script>
const NOW = __NOW__
const SECTIONS = __SECTIONS__
const DOCS = __DOCS__
const SOURCE = '__SOURCE__'
const STATUS = { wait: ['ينتظر قرارك', 's-wait'], you: ['دورك أنت', 's-you'], todo: ['لم يبدأ', 's-todo'] }
const SENDABLE = ['available', 'available_if_summoned', 'available_if_opened']
const MAX_BYTES = 4000
const ticks = {}
const picked = new Map()
const notes = {}
const opened = new Set()
const unsaved = new Map()
let stale = false
let db = null
let room = null
let selecting = false
let canSend = false
let saidTimer = null

function isChecked(item) { return !!ticks[item.id] }
function countItems(n) {
  if (n === 1) return 'بند واحد'
  if (n === 2) return 'بندان'
  const tail = n % 100
  if (tail >= 3 && tail <= 10) return n + ' بنود'
  if (tail >= 11) return n + ' بندًا'
  return n + ' بند'
}
function tickable(item) { return item.s in STATUS }

function noteOf(item) { return notes[item.id] || '' }
function noteShown(item) { return item.s === 'wait' || !!noteOf(item) || opened.has(item.id) }

// A render would drop the focus and the keyboard from a field mid-sentence, so a change that arrives then waits for the blur.
function refresh() {
  if (document.activeElement?.classList?.contains('note-in')) { stale = true; return }
  stale = false
  render()
}

async function saveNote(item, said) {
  clearTimeout(unsaved.get(item.id))
  unsaved.delete(item.id)
  const text = noteOf(item).trim()
  if (!db) { said.textContent = 'لن تُحفظ بعد إغلاق الصفحة.'; return }
  try {
    const doc = db.collection('notes').doc(item.id)
    if (text) await doc.set({ text, at: new Date().toISOString() })
    else await doc.delete()
    if (!unsaved.has(item.id)) said.textContent = text ? 'حُفظت' : ''
  } catch (e) { said.textContent = 'لم تُحفظ. اكتب حرفًا لإعادة المحاولة.' }
}

function buildNote(item) {
  const box = document.createElement('div')
  box.className = 'note'
  box.hidden = !noteShown(item)
  const input = document.createElement('textarea')
  input.className = 'note-in'
  input.rows = 1
  input.maxLength = 1000
  input.value = noteOf(item)
  input.placeholder = item.s === 'wait' ? 'قرارك…' : 'ملاحظتك…'
  input.setAttribute('aria-label', (item.s === 'wait' ? 'قرارك في: ' : 'ملاحظة على: ') + item.plain)
  const said = document.createElement('span')
  said.className = 'note-said'
  said.setAttribute('role', 'status')
  const fit = () => { input.style.height = 'auto'; input.style.height = input.scrollHeight + 2 + 'px' }
  input.addEventListener('input', () => {
    notes[item.id] = input.value
    said.textContent = ''
    fit()
    renderPickUi()
    clearTimeout(unsaved.get(item.id))
    unsaved.set(item.id, setTimeout(() => saveNote(item, said), 700))
  })
  input.addEventListener('blur', () => {
    if (unsaved.has(item.id)) saveNote(item, said)
    if (!noteOf(item).trim()) { opened.delete(item.id); if (item.s !== 'wait') stale = true }
    if (stale) setTimeout(refresh, 250)
  })
  box.append(input, said)
  requestAnimationFrame(fit)
  return box
}

function buildNoteButton(item) {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'note-btn'
  btn.textContent = '✎'
  btn.setAttribute('aria-label', 'أضف ملاحظة: ' + item.plain)
  btn.addEventListener('click', (e) => {
    e.preventDefault()
    e.stopPropagation()
    opened.add(item.id)
    render()
    document.getElementById('n-' + item.id)?.querySelector('textarea')?.focus()
  })
  return btn
}

function buildPickBox(item) {
  const box = document.createElement('input')
  box.type = 'checkbox'
  box.id = 'c-' + item.id
  box.checked = picked.has(item.id)
  box.setAttribute('aria-label', 'تحديد: ' + item.plain)
  box.addEventListener('click', (e) => e.stopPropagation())
  box.addEventListener('change', () => pick(item))
  return box
}

function buildRow(item, n, rowTag) {
  const row = document.createElement(rowTag)
  row.className = 'row'
  if (selecting) {
    row.appendChild(buildPickBox(item))
    row.addEventListener('click', (e) => {
      if (e.target.closest('a, .doclink')) return
      e.preventDefault()
      pick(item)
    })
  } else if (tickable(item)) {
    const box = document.createElement('input')
    box.type = 'checkbox'
    box.id = 'c-' + item.id
    box.checked = isChecked(item)
    box.setAttribute('aria-label', 'تم: ' + item.plain)
    box.addEventListener('click', (e) => e.stopPropagation())
    box.addEventListener('change', () => toggle(item, box.checked))
    row.appendChild(box)
  } else {
    row.appendChild(document.createElement('span'))
  }
  if (tickable(item)) {
    const rank = document.createElement('span')
    rank.className = 'rank' + (item.hot ? ' hot' : '')
    rank.textContent = String(n + 1)
    row.appendChild(rank)
  } else {
    row.appendChild(document.createElement('span'))
  }
  const title = document.createElement('span')
  title.className = 't'
  title.innerHTML = item.t
  row.appendChild(title)
  if (tickable(item)) {
    const [label, cls] = isChecked(item) ? ['تم', 's-done'] : STATUS[item.s]
    const pill = document.createElement('span')
    pill.className = 'pill ' + cls
    pill.textContent = label
    row.appendChild(pill)
  }
  if (!noteShown(item)) row.appendChild(buildNoteButton(item))
  return row
}

function renderNow() {
  const box = document.getElementById('nowText')
  box.innerHTML = NOW.items.length ? '' : '<p>لا شيء قيد البناء.</p>'
  for (const item of NOW.items) {
    const line = document.createElement('div')
    line.className = 'now-line'
    if (selecting) line.appendChild(buildPickBox(item))
    const text = document.createElement('p')
    text.innerHTML = item.t
    line.appendChild(text)
    if (!noteShown(item)) line.appendChild(buildNoteButton(item))
    box.appendChild(line)
    const note = buildNote(item)
    note.id = 'n-' + item.id
    box.appendChild(note)
  }
}

function render() {
  renderNow()
  renderPickUi()
  const root = document.getElementById('sections')
  const openSecs = new Set([...root.querySelectorAll('details.sec[open]')].map((d) => d.dataset.id))
  const openItems = new Set([...root.querySelectorAll('details.item[open]')].map((d) => d.dataset.id))
  const first = !root.children.length
  root.innerHTML = ''
  for (const sec of SECTIONS) {
    const left = sec.items.filter((i) => tickable(i) && !isChecked(i)).length
    const el = document.createElement('details')
    el.className = 'sec'
    el.dataset.id = sec.id
    el.open = first ? sec.open : openSecs.has(sec.id)
    const head = document.createElement('summary')
    const h2 = document.createElement('h2')
    h2.innerHTML = sec.title
    head.appendChild(h2)
    const count = document.createElement('span')
    count.className = 'count'
    const tickableCount = sec.items.filter(tickable).length
    count.textContent = sec.items.length ? countItems(sec.items.length) + (tickableCount && left !== tickableCount ? '، باقٍ ' + left : '') : ''
    head.appendChild(count)
    el.appendChild(head)
    const list = document.createElement('div')
    list.className = 'list'
    sec.items.forEach((item, n) => {
      const cls = 'item' + (isChecked(item) ? ' checked' : '') + (item.s === 'rule' || item.s === 'plan' ? ' rule' : '')
      if (item.d) {
        const it = document.createElement('details')
        it.className = cls
        it.dataset.id = item.id
        it.open = openItems.has(item.id)
        it.appendChild(buildRow(item, n, 'summary'))
        const body = document.createElement('div')
        body.className = 'body'
        body.innerHTML = item.d
        it.appendChild(body)
        list.appendChild(it)
      } else {
        const it = document.createElement('div')
        it.className = cls
        it.appendChild(buildRow(item, n, 'div'))
        list.appendChild(it)
      }
      // Beside the fold, not inside it, so a question's answer stays in sight when its details are shut.
      const note = buildNote(item)
      note.id = 'n-' + item.id
      list.appendChild(note)
    })
    if (sec.tables) {
      const box = document.createElement('div')
      box.className = 'tables'
      box.innerHTML = sec.tables
      list.appendChild(box)
    }
    el.appendChild(list)
    root.appendChild(el)
  }
}

async function toggle(item, value) {
  ticks[item.id] = value
  render()
  if (!db) return
  try { await db.collection('checks').doc(item.id).set({ done: value, at: new Date().toISOString() }) }
  catch (e) { document.getElementById('sync').textContent = 'لم يُحفظ تعليمك الأخير. حاول مرة أخرى.' }
}

// While the selection bar is up the dock is hidden, so the word goes on the bar. On the dock it clears itself, to give back the screen.
function say(text) {
  clearTimeout(saidTimer)
  document.getElementById(selecting ? 'barCount' : 'said').textContent = text
  if (!selecting && text) saidTimer = setTimeout(() => say(''), 8000)
}

function pick(item) {
  if (picked.has(item.id)) picked.delete(item.id)
  else picked.set(item.id, item)
  render()
  document.getElementById('c-' + item.id)?.focus({ preventScroll: true })
}

function setSelecting(on) {
  selecting = on
  if (!on) picked.clear()
  render()
}

function renderPickUi() {
  document.querySelector('.wrap').classList.toggle('selecting', selecting)
  document.querySelector('.wrap').classList.toggle('docked', canSend)
  document.getElementById('tools').hidden = !canSend || selecting
  document.getElementById('bar').hidden = !selecting
  const noted = notedItems().length
  const sendNoted = document.getElementById('sendNoted')
  sendNoted.textContent = 'أرسل كل الملاحظات' + (noted ? ' (' + noted + ')' : '')
  sendNoted.setAttribute('aria-label', 'أرسل كل البنود ذات الملاحظات: ' + countItems(noted))
  sendNoted.disabled = !noted
  const withNotes = [...picked.values()].filter((i) => noteOf(i).trim()).length
  document.getElementById('barCount').textContent = picked.size ? 'حددت ' + picked.size + ' من البنود' + (withNotes ? '، ' + withNotes + ' منها بملاحظة' : '') : 'اضغط البنود التي تريدها'
  document.getElementById('sendNow').disabled = !picked.size
  document.getElementById('sendStage').disabled = !picked.size
}

// The platform refuses a whole send over its limits or with format characters, so clean first and shed detail before words.
// A note is the owner's own answer and is never shed: past the limit the send stops and asks them to pick fewer.
const clean = (text) => String(text).replace(/[\p{Cc}\p{Cf}\p{Co}]/gu, ' ').replace(/\s+/g, ' ').trim()

function notedItems() { return [...NOW.items, ...SECTIONS.flatMap((s) => s.items)].filter((i) => noteOf(i).trim()) }

function itemsPayload(list) {
  const items = list.map((i) => {
    const entry = { id: i.id, section: clean(i.sec), text: clean(i.plain), details: (i.dp || []).map(clean).slice(0, 40) }
    const note = clean(noteOf(i))
    if (note) entry.note = note
    return entry
  })
  const data = { label: list.length + ' من بنود المتابعة', action: 'execute', source: SOURCE, items }
  const size = () => new TextEncoder().encode(JSON.stringify(data)).length
  if (size() > MAX_BYTES) items.forEach((i) => { delete i.details })
  if (size() > MAX_BYTES) items.forEach((i) => { i.text = i.text.slice(0, 70) })
  return size() > MAX_BYTES || items.length > 60 ? null : data
}

function sendPicked(deliver) {
  const sent = new Map(picked)
  const restore = (text) => { sent.forEach((v, k) => picked.set(k, v)); selecting = true; render(); say(text) }
  sendItems([...picked.values()], deliver, 'البنود كثيرة على رسالة واحدة. قلّل التحديد.', restore)
}

function sendItems(list, deliver, tooMany, restore) {
  const data = itemsPayload(list)
  if (!data) { say(tooMany); return }
  const onStatus = (s) => { if (s.state === 'failed') restore('لم تصل البنود إلى الجلسة. حاول مرة أخرى.') }
  // Called straight from the press, nothing awaited first: the platform proves the click from this very call.
  room.sendToClaudeSession(data, { deliver, attachPresence: false, onStatus }).then(() => {
    setSelecting(false)
    say(deliver === 'send' ? 'أُرسلت. راجع الشات، وقد يطلب منك تأكيد الإرسال.' : 'وُضعت في رسالتك. أضف ما تريد ثم أرسلها.')
  }).catch((e) => {
    if (e?.code === 'claude_unavailable' && deliver === 'send') {
      room.sendToClaudeSession(data, { deliver: 'stage', attachPresence: false }).then(() => {
        setSelecting(false)
        say('وُضعت في رسالتك. أرسلها من الشات.')
      }).catch(() => say('لا توجد جلسة مفتوحة تستقبلها الآن. افتح الصفحة بجانب الشات.'))
      return
    }
    say(e?.code === 'rate_limited' ? 'انتظر لحظة ثم أعد الإرسال.' : 'لم تصل البنود. حاول مرة أخرى.')
  })
}

function openDoc(index) {
  const doc = DOCS[index]
  if (!doc) return
  document.getElementById('docTitle').textContent = doc.title
  document.getElementById('docBody').innerHTML = doc.html
  document.getElementById('docBody').scrollTop = 0
  const dialog = document.getElementById('doc')
  if (!dialog.open) dialog.showModal()
}

document.addEventListener('click', (e) => {
  const link = e.target.closest?.('.doclink')
  if (!link) return
  e.preventDefault()
  e.stopPropagation()
  openDoc(Number(link.dataset.doc))
}, true)
const docDialog = document.getElementById('doc')
docDialog.addEventListener('click', (e) => { if (e.target === docDialog) docDialog.close() })
document.getElementById('docClose').addEventListener('click', () => docDialog.close())
document.getElementById('pickToggle').addEventListener('click', () => setSelecting(true))
document.getElementById('sendNoted').addEventListener('click', () => sendItems(notedItems(), 'send', 'الملاحظات كثيرة على رسالة واحدة. حدد بعضها وأرسلها.', say))
document.getElementById('pickCancel').addEventListener('click', () => setSelecting(false))
document.getElementById('sendNow').addEventListener('click', () => sendPicked('send'))
document.getElementById('sendStage').addEventListener('click', () => sendPicked('stage'))
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && selecting && !docDialog.open) setSelecting(false) })

document.getElementById('nowNext').textContent = NOW.next
render()

;(async () => {
  try {
    db = await window.claude?.use?.('db')
    if (!db) return
    db.collection('checks').onSnapshot((snap) => {
      for (const d of snap.docs) { const v = d.data(); if (v && typeof v.done === 'boolean') ticks[d.id] = v.done }
      refresh()
    }, () => {})
    db.collection('notes').onSnapshot((snap) => {
      const seen = new Set()
      let changed = false
      for (const d of snap.docs) {
        seen.add(d.id)
        const text = d.data()?.text
        if (typeof text !== 'string' || unsaved.has(d.id) || (notes[d.id] || '').trim() === text) continue
        notes[d.id] = text
        changed = true
      }
      for (const id of Object.keys(notes)) {
        if (seen.has(id) || unsaved.has(id) || !notes[id].trim()) continue
        delete notes[id]
        changed = true
      }
      if (changed) refresh()
    }, () => {})
  } catch (e) { db = null }
})()

;(async () => {
  try {
    room = await window.claude?.use?.('room')
    if (!room) return
    const state = await room.canSendToClaudeSession()
    if (!SENDABLE.includes(state)) return
    canSend = true
    renderPickUi()
    // Beside no conversation a staged send would take the owner away from this page to a new chat.
    if (state === 'available_if_summoned') document.getElementById('sendStage').hidden = true
  } catch (e) { room = null }
})()
</script>
"""


def count_ar(n, forms):
    """Arabic counts agree with their number: one, two, 3 to 10, 11 to 99, then 100 and its kin."""
    one, two, few, many, hundred = forms
    if n == 1:
        return one
    if n == 2:
        return two
    tail = n % 100
    if 3 <= tail <= 10:
        return f"{n} {few}"
    return f"{n} {many if tail >= 11 else hundred}"


def sensitive_lines(text):
    """Where a text looks like it holds a secret or a person's details: (line, kind), never the value."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        kinds = [kind for kind, pattern in SENSITIVE if pattern.search(line)]
        for match in ASSIGNED_SECRET.finditer(line):
            value = match.group("quoted") or match.group("bare") or match.group("token")
            if not PLACEHOLDER.match(value):
                kinds.append("secret value")
                break
        for match in IPV4.finditer(line):
            try:
                if ipaddress.ip_address(match.group()).is_global:
                    kinds.append("public IP address")
                    break
            except ValueError:
                pass
        found += [(number, kind) for kind in kinds]
    return found


def refuse(rel, reason):
    REFUSED[rel] = reason


def doc_index(rel, any_md):
    """Copy a plan file into the page once and return its place, or None if it must stay out."""
    rel = rel.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    if rel in DOCS:
        return list(DOCS).index(rel)
    # Text inside a copied file links to what is already here and never brings in more.
    if READING_DOCS or rel in REFUSED:
        return None
    if DOC_ROOT is None or rel.startswith("/") or ":" in rel or ".." in rel.split("/"):
        return None
    if not any_md and not rel.startswith("plans/"):
        return None
    full = os.path.join(DOC_ROOT, *rel.split("/"))
    if not os.path.isfile(full):
        return None
    root = os.path.realpath(DOC_ROOT)
    if os.path.commonpath([root, os.path.realpath(full)]) != root:
        return refuse(rel, "it points outside the project")
    if os.path.getsize(full) > MAX_DOC_BYTES:
        return refuse(rel, f"it is over {MAX_DOC_BYTES // 1024} KB")
    try:
        with open(full, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as error:
        return refuse(rel, f"it could not be read ({type(error).__name__})")
    if sum(len(t.encode()) for t in DOCS.values()) + len(text.encode()) > MAX_ALL_DOCS_BYTES:
        return refuse(rel, f"the copied files would pass {MAX_ALL_DOCS_BYTES // 1024} KB")
    found = sensitive_lines(text)
    if found and rel not in ALLOWED:
        shown = ", ".join(f"line {n}: {kind}" for n, kind in found[:8])
        more = f", and {len(found) - 8} more" if len(found) > 8 else ""
        return refuse(rel, shown + more)
    DOCS[rel] = text
    return list(DOCS).index(rel)


def read_docs():
    """Turn the named files into page text, once all of them are known, so they can link to each other."""
    global READING_DOCS
    READING_DOCS = True
    for rel, text in list(DOCS.items()):
        DOCS[rel] = doc_entry(rel, text)
    READING_DOCS = False


def inline(text, any_md=False):
    def replace(m):
        code, label, target, bare = m.groups()
        rel = target or bare or (code if code and code.endswith(".md") else None)
        index = doc_index(rel, any_md) if rel else None
        if index is None:
            return f"<code>{code}</code>" if code is not None else m.group(0)
        shown = f"<code>{code}</code>" if code is not None else (label or bare)
        return f'<button type="button" class="doclink" data-doc="{index}">{shown}</button>'

    out = html.escape(text, quote=True)
    out = re.sub(r"`([^`]+)`|\[([^\]]+)\]\(([^)\s]+\.md)\)|(?<![\w/.-])([\w./-]+\.md)(?![\w/-])", replace, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)


def markdown_html(lines):
    """Just enough markdown for a plan file; the tracker's own syntax stays in parse()."""
    out, para, table, lists = [], [], [], []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
        para.clear()
        if table:
            out.append(table_html(table))
        table.clear()

    def close_lists(level=0):
        while len(lists) > level:
            out.append(f"</{lists.pop()}>")

    fence = None
    for raw in lines:
        stripped = raw.strip()
        if fence is not None:
            if stripped.startswith("```"):
                out.append(f"<pre><code>{html.escape(chr(10).join(fence))}</code></pre>")
                fence = None
            else:
                fence.append(raw.rstrip())
            continue
        item = re.match(r"(\s*)([-*]|\d+\.) (.*)", raw)
        if item:
            flush()
            level = len(item.group(1)) // 2 + 1
            tag = "ol" if item.group(2)[0].isdigit() else "ul"
            close_lists(level)
            while len(lists) < level:
                out.append(f"<{tag}>")
                lists.append(tag)
            out.append(f"<li>{inline(item.group(3))}</li>")
            continue
        close_lists()
        if stripped.startswith("|"):
            if para:
                flush()
            table.append(stripped)
            continue
        heading = re.match(r"(#{1,4}) (.*)", stripped)
        rule = re.fullmatch(r"-{3,}", stripped)
        note = re.fullmatch(r"_[^_].*_", stripped)
        if not (heading or rule or note or not stripped or stripped.startswith(("```", "<!--"))):
            if table:
                flush()
            para.append(stripped)
            continue
        flush()
        if stripped.startswith("```"):
            fence = []
        elif heading:
            out.append(f"<h{len(heading.group(1)) + 2}>{inline(heading.group(2))}</h{len(heading.group(1)) + 2}>")
        elif rule:
            out.append("<hr>")
        elif note:
            out.append(f'<p class="note">{inline(stripped[1:-1])}</p>')
    flush()
    close_lists()
    return "".join(out)


def doc_entry(rel, text):
    lines = text.splitlines()
    title = plain(lines[0][2:]).strip() if lines and lines[0].startswith("# ") else rel
    return {"path": rel, "title": title, "html": markdown_html(lines[1:] if title != rel else lines)}


def plain(text):
    return re.sub(r"[`*]", "", text)


def table_html(rows):
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-+:?", c) for c in r)]
    head = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def parse(lines):
    title, notes, sections = "", [], []
    current = None
    top = ""
    table = []

    def flush_table():
        if table and current is not None:
            current["tables"] += table_html(table)
        table.clear()

    def new_section(name, group=None):
        nonlocal current
        flush_table()
        label = group or name
        current = {
            "id": "s" + hashlib.sha1((name + (group or "")).encode()).hexdigest()[:8],
            "title": inline(label),
            "status": STATUS_BY_SECTION.get(name, "todo"),
            "top": name,
            "open": name in OPEN_BY_DEFAULT,
            "items": [],
            "tables": "",
        }
        sections.append(current)

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            flush_table()
            continue
        if stripped.startswith("|"):
            table.append(stripped)
            continue
        flush_table()
        if stripped.startswith("# "):
            title = stripped[2:]
        elif stripped.startswith("## "):
            top = stripped[3:]
            new_section(top)
        elif stripped.startswith("### ") and top:
            new_section(top, stripped[4:])
        elif re.match(r"\s{2,}- ", raw) and current and current["items"]:
            current["items"][-1]["details"].append(stripped[2:])
        elif current is None:
            notes.append(stripped.strip("_"))
        else:
            # A plain line inside a section is an item too, so nothing written in the file is lost.
            text = stripped[2:] if stripped.startswith("- ") else stripped
            hot = text.startswith("! ")
            text = text[2:] if hot else text
            digest = hashlib.sha1((current["top"] + text).encode()).hexdigest()[:10]
            current["items"].append({"id": "i" + digest, "text": text, "hot": hot, "details": []})
    flush_table()
    return title, " ".join(notes), sections


def render(title, note, sections, source):
    now_items, payload, waiting, yours, first_open_group = [], [], 0, 0, True
    for sec in sections:
        any_md = sec["top"] == PLANS_SECTION
        sec_name = plain(html.unescape(re.sub(r"<[^>]+>", "", sec["title"])))
        if sec["top"] == "الآن":
            now_items += [{"id": i["id"], "t": inline(i["text"]), "plain": plain(i["text"]), "sec": sec_name,
                           "dp": [plain(d) for d in i["details"]]} for i in sec["items"]]
            continue
        if not sec["items"] and not sec["tables"]:
            continue
        if sec["top"] == "مفتوح" and first_open_group:
            sec["open"] = True
            first_open_group = False
        items = []
        for item in sec["items"]:
            body = ""
            if item["details"]:
                body = "<ul>" + "".join(f"<li>{inline(d, any_md)}</li>" for d in item["details"]) + "</ul>"
            items.append({"id": item["id"], "s": sec["status"], "hot": item["hot"],
                          "t": inline(item["text"], any_md), "plain": plain(item["text"]), "d": body,
                          "sec": sec_name, "dp": [plain(d) for d in item["details"]]})
        waiting += len(items) if sec["status"] == "wait" else 0
        yours += len(items) if sec["status"] == "you" else 0
        payload.append({"id": sec["id"], "title": sec["title"], "open": sec["open"],
                        "items": items, "tables": sec["tables"]})
    owed = ([count_ar(waiting, DECISION_FORMS)] if waiting else []) + ([count_ar(yours, TASK_FORMS)] if yours else [])
    next_line = f"ينتظرك: {' و'.join(owed)}." if owed else "لا شيء ينتظرك الآن."
    as_json = lambda value: json.dumps(value, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    note_html = inline(note)
    read_docs()
    # One pass, so a line that happens to contain a placeholder's name cannot pull another block into itself.
    fill = {
        "TITLE": html.escape(title), "NOTE": note_html, "SOURCE": html.escape(source),
        "NOW": as_json({"items": now_items, "next": next_line}),
        "SECTIONS": as_json(payload), "DOCS": as_json(list(DOCS.values())),
    }
    return re.sub(r"__(TITLE|NOTE|SOURCE|NOW|SECTIONS|DOCS)__", lambda m: fill[m.group(1)], PAGE)


def project_path(path):
    return os.path.relpath(os.path.abspath(path), DOC_ROOT).replace("\\", "/")


def main():
    global DOC_ROOT
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Render a TRACKER.md into its phone page.")
    parser.add_argument("--ids", action="store_true", help="print each item's id and text, and write nothing")
    parser.add_argument("--allow", action="append", default=[], metavar="PATH",
                        help="pass one file through the sensitive-content check, after a person has read it")
    parser.add_argument("tracker")
    parser.add_argument("output", nargs="?")
    args = parser.parse_args()
    if not args.ids and not args.output:
        parser.error("give an output file, or --ids")
    folder = os.path.dirname(os.path.abspath(args.tracker))
    DOC_ROOT = os.path.dirname(folder) if os.path.basename(folder) == "plans" else folder
    ALLOWED.update(project_path(p) if os.path.exists(p) else p.replace("\\", "/") for p in args.allow)
    try:
        with open(args.tracker, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as error:
        sys.exit(f"cannot read {args.tracker}: {error}")
    title, note, sections = parse(text.splitlines())
    if args.ids:
        for sec in sections:
            for item in sec["items"]:
                print(item["id"], plain(item["text"]))
        return
    shown = project_path(args.tracker)
    found = sensitive_lines(text)
    if found and shown not in ALLOWED:
        for number, kind in found:
            print(f"{shown}: line {number}: {kind}", file=sys.stderr)
        sys.exit(2)
    page = render(title or os.path.basename(args.tracker), note, sections, shown)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    for rel in DOCS:
        print(f"copied {rel}")
    for rel, reason in REFUSED.items():
        print(f"left out {rel}: {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
