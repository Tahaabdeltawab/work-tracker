# work-tracker

A [Claude Code](https://claude.com/claude-code) skill that keeps one small tracking file per project and renders it into a page you can read, tick and answer from your phone.

ملف متابعة واحد لكل مشروع، يكتبه الوكيل ويحدّثه مع كل خطوة، وتقرؤه أنت صفحةً جميلة على هاتفك: تطوي البنود، وتعلّم ما انتهى، وتكتب قرارك، وترسل ما تختاره إلى الجلسة.

## Why

Agents leave handoff notes, ledgers and to-do files behind, and after a while nobody can say what is open. This skill replaces all of them with one file that grows only when real work grows: an item is one line, a finished item is deleted because git keeps it, and past about 100 lines the agent must shrink it before adding more.

## Install

```bash
git clone https://github.com/Tahaabdeltawab/work-tracker ~/.claude/skills/work-tracker
```

Then ask Claude Code to set up tracking in a project, or say «ملف المتابعة». Python 3.8 or newer, with no packages to install.

## The file

```markdown
# متابعة أعمال مشروعي
<!-- page: https://claude.ai/artifact/... -->

## الآن
- Building the sign-up form.

## ينتظر قرارك
- Free plan: 10 students or 20?

## دورك أنت
- Pay for the domain.

## مفتوح
### Billing
- ! Refund button charges twice.
- Invoice PDF.
  - Only what the owner needs in order to decide goes here.

## قرارات سارية
- Prices stay in EGP.

## الخطط
- `plans/ROADMAP.md`: the next quarter.

## الأرشيف
```

## The page

```bash
python scripts/render_page.py plans/TRACKER.md tracker.html
```

| In the file | On the page |
|---|---|
| `- ! text` | An urgent item, with a red number |
| Indented `  - detail` | The item folds open to show it |
| `###` group | Its own folding group |
| A table | Shown at the end of its group |
| A plan's path | A link that opens the plan's text in a dialog |

Published as a Claude artifact, the page saves ticks and notes, and can send picked items to the session. Anywhere else it opens as a plain page: ticks and notes last only until it closes, and the send control stays hidden.

## What it will not put on the page

A named plan's whole text is copied into the page, so the renderer guards it:

- Only files the tracker itself names are copied. A path inside a copied file never brings another file in.
- A file stays out if it looks like it holds a key, a password, a signed token, a public IP address, an SSH key path, a phone number or a personal email address, or if it is over 128 KB. The renderer reports the line and the kind, never the value.
- A tracker that trips the same check writes no page and exits with status 2.
- `--allow <path>` passes one file, after a person has read it.

This is a net, not a proof. It catches shapes, not meaning, and it will sometimes refuse a harmless file. Read a plan before you name it.

## Limits

- The page and the section names are Arabic and right to left. Items can be in any language.
- Saved ticks, notes and sending need the Claude artifact runtime.

## Tests

```bash
python scripts/test_render_page.py
```

## License

[MIT](LICENSE)
