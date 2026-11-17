# SPDX-License-Identifier: AGPL-3.0-only
import re
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from docx.document import Document as WordDocument
from docx.shared import Inches
from docx.text.paragraph import Paragraph
from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token

WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def clean(text: str) -> str:
    return "".join(
        char
        for char in text
        if char in "\t\n\r"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
    )


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "chat"


def latex(state: StateInline, silent: bool) -> bool:
    for start, end in ((r"\(", r"\)"), (r"\[", r"\]"), ("$$", "$$"), ("$", "$")):
        if state.src.startswith(start, state.pos):
            stop = state.src.find(end, state.pos + len(start))
            if stop < 0:
                continue
            if not silent:
                token = state.push("text", "", 0)
                token.content = state.src[state.pos : stop + len(end)]
            state.pos = stop + len(end)
            return True
    return False


def inline(paragraph: Paragraph, tokens: list[Token]) -> None:
    bold = italic = strike = False
    links: list[str] = []
    for token in tokens:
        match token.type:
            case "strong_open" | "strong_close":
                bold = token.type == "strong_open"
            case "em_open" | "em_close":
                italic = token.type == "em_open"
            case "s_open" | "s_close":
                strike = token.type == "s_open"
            case "link_open":
                links.append(token.attrGet("href") or "")
            case "link_close":
                if links:
                    paragraph.add_run(f" [{clean(links.pop())}]")
            case "softbreak" | "hardbreak":
                paragraph.add_run("\n")
            case _:
                if token.children:
                    inline(paragraph, token.children)
                elif token.content:
                    run = paragraph.add_run(clean(token.content))
                    run.bold, run.italic, run.font.strike = bold, italic, strike
                    if token.type == "code_inline":
                        run.font.name = "Courier New"


def markdown(document: WordDocument, text: str) -> None:
    parser = MarkdownIt("commonmark", {"html": False}).enable(
        ["table", "strikethrough"]
    )
    parser.inline.ruler.before("escape", "latex_literal", latex)
    tokens = parser.parse(clean(text))
    lists: list[int | None] = []
    item_starts: list[bool] = []
    quote = 0
    paragraph: Paragraph | None = None
    table = None
    header = False
    cell_index = 0
    for position, token in enumerate(tokens):
        match token.type:
            case "bullet_list_open":
                lists.append(None)
                item_starts.append(False)
            case "ordered_list_open":
                lists.append(int(token.attrGet("start") or 1))
                item_starts.append(False)
            case "bullet_list_close" | "ordered_list_close":
                lists.pop()
                item_starts.pop()
            case "list_item_open":
                item_starts[-1] = True
            case "list_item_close":
                if lists[-1] is not None:
                    lists[-1] += 1
            case "blockquote_open":
                quote += 1
            case "blockquote_close":
                quote -= 1
            case "paragraph_open" | "heading_open":
                if token.type == "heading_open":
                    paragraph = document.add_heading(
                        level=min(int(token.tag[1:]) + 1, 4)
                    )
                else:
                    style = None
                    if lists and lists[-1] is None and item_starts[-1]:
                        depth = min(len(lists), 3)
                        style = "List Bullet" + (f" {depth}" if depth > 1 else "")
                    paragraph = document.add_paragraph(style=style)
                    if lists and lists[-1] is not None and item_starts[-1]:
                        paragraph.add_run(f"{lists[-1]}. ")
                if lists:
                    item_starts[-1] = False
                if quote or lists:
                    paragraph.paragraph_format.left_indent = Inches(
                        0.25 * (quote + min(len(lists), 3))
                    )
            case "inline":
                if paragraph is None:
                    paragraph = document.add_paragraph()
                inline(paragraph, token.children or [])
                if table is not None and header:
                    for run in paragraph.runs:
                        run.bold = True
            case "paragraph_close" | "heading_close":
                paragraph = None
            case "fence" | "code_block":
                paragraph = document.add_paragraph()
                paragraph.add_run(clean(token.content)).font.name = "Courier New"
                paragraph = None
            case "hr":
                document.add_paragraph()
            case "table_open":
                first_row = tokens[position + 1 :]
                end = next(
                    i for i, part in enumerate(first_row) if part.type == "tr_close"
                )
                columns = sum(
                    part.type in {"th_open", "td_open"} for part in first_row[:end]
                )
                table = document.add_table(rows=0, cols=columns)
                table.style = "Table Grid"
            case "tr_open":
                assert table is not None
                cells = table.add_row().cells
                cell_index = 0
            case "th_open" | "td_open":
                paragraph = cells[cell_index].paragraphs[0]
                cell_index += 1
                header = token.type == "th_open"
            case "th_close" | "td_close":
                paragraph = None
            case "tr_close":
                pass
            case "table_close":
                table = None
            case _:
                if token.content:
                    document.add_paragraph(clean(token.content))


def export_word(
    conversation: dict[str, Any], zone: str, now: datetime | None = None
) -> bytes:
    time_zone = ZoneInfo(zone)
    exported = (now or datetime.now(UTC)).astimezone(time_zone)

    def stamp(value: datetime) -> str:
        return value.astimezone(time_zone).strftime("%d %b %Y %H:%M")

    document = Document()
    document.add_paragraph(clean(conversation["title"]), style="Title")
    document.add_paragraph(
        f"Open Office Harness · conversation started "
        f"{stamp(conversation['created_at'])} · "
        f"exported {stamp(exported)} ({exported.tzname()})"
    )
    for message in conversation["messages"]:
        if message["outcome"] != "completed" or not message["content"]:
            continue
        assistant = message["role"] == "assistant"
        label = document.add_paragraph()
        label.add_run("Assistant" if assistant else "You").bold = True
        label.add_run(f" · {stamp(message['created_at'])}")
        if assistant and message.get("tier") is not None:
            label.add_run(f" · tier {message['tier']}")
            if message.get("model_title"):
                label.add_run(f" · {clean(message['model_title'])}")
        if assistant:
            markdown(document, message["content"])
        else:
            document.add_paragraph(clean(message["content"]))
            if message.get("picture"):
                document.add_paragraph(
                    f"[Picture attached: {clean(message['picture']['file_name'])}]"
                )
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
