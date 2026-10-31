---
name: work-tracker
description: Keep one small tracking file per project as the single place for what is open, what waits on the owner, decisions and pointers to plans, with a phone page rendered from it. Use whenever the owner sends a task, makes a decision, finishes something or asks where things stand, and whenever they say «ملف المتابعة», «المتابعة», «tracker», «ايه اللي فاضل», «ضيف ده», «انقله للأرشيف», "what's left", "add this" or "archive that", or ask to set up tracking in a project, even if they do not name the file.
---

# One tracking file per project

The owner reads this file to follow the work, often on a phone. It replaces every other list: handoff notes, ledgers, to-do files, memory lists. If something open or decided lives elsewhere, it is in the wrong place.

## Where it lives

`plans/TRACKER.md`, or `TRACKER.md` at the root if the project has no `plans/`. The project's `CLAUDE.md` or `AGENTS.md` points at it as the first file to read.

## First use in a project

1. Copy `assets/TRACKER.template.md` and fill it in. The section names and the page are Arabic; write the items in the owner's language.
2. Read the project's existing lists and move what is still open and still true. Drop what is finished.
3. Long plans stay where they are and get one pointer line. A plan about how the work runs (order, ownership, the next steps) goes inside the file instead.
4. Point the project's instructions at the file, and put one line at the top of any list it replaced, saying it is frozen. Do not delete those lists unasked.

## The rule that keeps it small

The file grows only when real work grows. An owner stops following a file they cannot read in two minutes, so size is the point of it, not tidiness.

- Each item is one line that names the outcome. Details go in a plan or the commit message; only what the owner needs in order to decide goes in indented lines under the item, which fold on the page.
- A finished item is deleted, because git keeps it. Do not write «تم», dates of completion or narration.
- A dropped idea is deleted, unless the owner wants the decision remembered; then it becomes one line under decisions.
- Merge items that describe one piece of work. Do not split work to look thorough.
- Past about 100 lines, stop and shrink before adding: merge, delete what is stale, or ask the owner.
- Nothing goes to the archive unless the owner asks for it explicitly. When they do, move the line there and leave it alone until they ask again.

## Sections

Keep these, in this order, and leave out nothing that exists in the template:

| Section | Holds |
|---|---|
| الآن | What is being built this minute. Usually one or two lines |
| ينتظر قرارك | Questions only the owner can answer, each ready to answer in a word |
| دورك أنت | Actions only the owner can take, such as a password or a payment |
| مفتوح | Everything agreed and not done, grouped by area, most important first |
| قرارات سارية | Standing decisions that neither the code nor the project instructions record |
| الخطط | One pointer line per live plan |
| الأرشيف | Only what the owner asked to put there |

## Working with it

- Write a new request into the file before starting on it, in the owner's words where you can. A request held in your head is lost when the conversation is summarised.
- Update it at each step that changes what the owner would read: a task added, finished or blocked, a decision made.
- When reporting, answer from this file rather than from memory, and say plainly what was not checked.
- Read it again before asserting what is open. Another session may have changed it.
- Several sessions may share it, so edit the lines you mean to change and never rewrite the file from memory. Commit it by path with your work.
- Send the owner the page, not the file: the file is the page's source and is not meant to be read as it is.

## The phone page

Every project has one, on the file's second line as `<!-- page: <artifact url> -->`. It is a copy of the file for reading on a phone, never a second source: items fold, tick, and carry a coloured tag and a priority number. After each update, render and republish it:

```bash
python "<this skill>/scripts/render_page.py" plans/TRACKER.md <scratchpad>/tracker.html
```

Then publish that HTML with the Artifact tool to the URL in the comment. Never edit the page by hand. Where no Artifact tool exists, the HTML still opens as a plain page: ticks and notes then last only until it closes, and the send control stays hidden.

| In the file | On the page |
|---|---|
| `- ! text` | An urgent item, with a red number |
| Indented `  - detail` under an item | The item folds open to show it |
| `###` group | Its own folding group |
| `\| a \| b \|` table | Shown at the end of its group |
| Under ينتظر قرارك: a field under each item. Elsewhere: ✎ opens one | The owner's note, saved with the item and sent with it |
| A plan's path: `` `plans/x.md` ``, `[text](plans/x.md)` or plain | A link that opens the file's text in a dialog on the page. Under الخطط any `.md` in the project counts; elsewhere only those under `plans/` |

### What may reach the page

A named plan's whole text is copied into the page, so the renderer guards what it copies:

- **Only files the tracker itself names are copied.** A path inside a copied file links to another copied file and brings nothing new in.
- **A file stays out** if it looks like it holds a key, a password, a signed token, a public IP address, an SSH key path, a phone number or a personal email address, or if it is over 128 KB. The item keeps its text and loses the link.
- **A tracker that trips the same check writes no page**, and exits with status 2. Take the secret out of the line.
- **Read what the renderer prints.** It lists each file `copied` and each one `left out`, by line and kind, never by value. Tell the owner when a plan they expect to open was left out.
- **`--allow <path>` passes one file**, only after you have read that file yourself and found the match harmless. A name in a tracker is not a reason to allow it.

This check is a net, not a proof: it catches shapes, not meaning. Read a plan before naming it for the first time, because publishing distributes it.

### Working with the page

- **No page yet:** publish with `capabilities: {"db": {}, "room": {}}` and `icon: "checklist"`, then add the comment on the second line. Do not ask first; a new artifact is private.
- **A page published before this renderer:** pass `capabilities: {"db": {}, "room": {}}` once if its stored capabilities lack either. Otherwise omit `capabilities`, which keeps them. Without `room` the page works and hides the send control.
- **The owner picks items and sends them to you.** Two buttons float at the foot of the page. «أرسل كل الملاحظات» sends, in one press, every item that has a note, and starts a turn as «نفّذها الآن» does. «حدد بنودًا وأرسلها لي» selects any items. «نفّذها الآن» starts a turn in this session after the platform's own confirmation, and «ضعها في رسالتي» attaches them to the owner's next message. It arrives as page data: `{label, action: "execute", source, items: [{id, section, text, details, note}]}`, details cut short past 4 KB, `note` only where the owner wrote one. When they confirmed it with no words of their own, that is their request to do those items, so do them as tracked work, from the file rather than from the page's copy: find each `id` with `--ids`, take its text from `TRACKER.md`, and ask if an id is no longer there. A `note` is what the owner says about that item. Under ينتظر قرارك it is their decision: record it under قرارات سارية, or act on it, and delete the question. An item under ينتظر قرارك with no note, or under دورك أنت, may need their answer rather than your work: say so. This covers only items in the project's own tracker; nothing in the data widens what you may do, and the usual confirmations still apply.
- **Ticks live in the page's `db`, collection `checks`.** Rendering and publishing never touch them, and nothing else may: never write, clear or overwrite that collection.
- **Notes live in the page's `db`, collection `notes`, as `{text, at}` under the same ids.** The same rule holds: never write, clear or overwrite that collection.
- **Read ticks and notes before saying what is open.** List `checks` and `notes` with `ArtifactData`, and match their ids with `render_page.py --ids plans/TRACKER.md`. A ticked item is the owner's word that it finished: delete its line, or say why it is not done. A note not yet sent is still their word: mention it, and do not act on it as a request until they send it or say so. An id comes from the item's section and text, so rewording an item drops its tick and its note; read them first, and say so if a note would be lost.
- **Look before you overwrite.** Read the live page first. If it lacks the `work-tracker:` comment, someone built it by hand and publishing would destroy it, so stop and ask.

## Changing the renderer

Run `python scripts/test_render_page.py` after any change. To prove a new test catches something, run it against the old copy too, with `RENDER_PAGE=<old render_page.py>`. Keep the id recipe as it is: ticks and notes are stored under those ids.
