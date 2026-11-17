# SPDX-License-Identifier: AGPL-3.0-only
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID

import pytest
from conftest import Harness
from docx import Document

from harness_api.word_export import WORD_MIME, export_word, slug

NOW = datetime(2026, 11, 17, 1, 52, tzinfo=UTC)


def conversation() -> dict[str, Any]:
    return {
        "title": "Test conversation",
        "created_at": NOW,
        "messages": [
            {
                "role": "user",
                "content": "* literal *\n# literal\none line\nsecond line",
                "outcome": "completed",
                "created_at": NOW,
                "picture": {"file_name": "picture.png"},
            },
            {
                "role": "assistant",
                "outcome": "completed",
                "tier": 2,
                "model_title": "Example model",
                "created_at": NOW,
                "thinking": "PRIVATE THINKING",
                "reasoning_state": {"opaque": "PRIVATE"},
                "content": """# Heading

#### Deep heading

**bold** and *italic* and ~~strike~~ and `inline code`.

- First
  - Nested
    - Third

3. Number three
4. Number four

Separate paragraph.

1. Restart one
2. Restart two

| Header | Other |
| --- | --- |
| Cell | Value |

```text
code line 1
code line 2
```

    indented code

> Quoted text

[Example](https://example.invalid/page)

---

<div>raw HTML</div>

LaTeX: \\(a_b\\) and $a_b$.

bad\x00characters
""",
            },
            {
                "role": "assistant",
                "content": "FAILED BODY",
                "outcome": "failed",
                "created_at": NOW,
            },
            {
                "role": "assistant",
                "content": "",
                "outcome": "completed",
                "created_at": NOW,
            },
        ],
    }


def test_word_contents_and_formatting() -> None:
    document = Document(BytesIO(export_word(conversation(), "Asia/Kuala_Lumpur", NOW)))
    paragraphs = document.paragraphs
    texts = [paragraph.text for paragraph in paragraphs]
    joined = "\n".join(texts)
    assert paragraphs[0].style.name == "Title" and texts[0] == "Test conversation"
    assert (
        texts[1] == "Open Office Harness · conversation started 17 Nov 2026 09:52 · "
        "exported 17 Nov 2026 09:52 (+08)"
    )
    assert texts[2] == "You · 17 Nov 2026 09:52"
    assert paragraphs[2].runs[0].bold
    assert texts[3] == "* literal *\n# literal\none line\nsecond line"
    assert "Assistant · 17 Nov 2026 09:52 · tier 2 · Example model" in texts
    assert "[Picture attached: picture.png]" in texts
    assert (
        "Heading" in texts
        and next(p for p in paragraphs if p.text == "Heading").style.name == "Heading 2"
    )
    assert (
        next(p for p in paragraphs if p.text == "Deep heading").style.name
        == "Heading 4"
    )
    assert (
        next(p for p in paragraphs if p.text == "Nested").style.name == "List Bullet 2"
    )
    assert (
        next(p for p in paragraphs if p.text == "Third").style.name == "List Bullet 3"
    )
    assert [text for text in texts if text[:2] in {"1.", "2.", "3.", "4."}] == [
        "3. Number three",
        "4. Number four",
        "1. Restart one",
        "2. Restart two",
    ]
    assert len(document.tables) == 1
    table = document.tables[0]
    assert [[cell.text for cell in row.cells] for row in table.rows] == [
        ["Header", "Other"],
        ["Cell", "Value"],
    ]
    assert table.rows[0].cells[0].paragraphs[0].runs[0].bold
    code = next(p for p in paragraphs if p.text.startswith("code line 1"))
    assert code.text == "code line 1\ncode line 2\n"
    assert code.runs[0].font.name == "Courier New"
    assert "indented code\n" in texts
    assert (
        next(
            p for p in paragraphs if p.text == "Quoted text"
        ).paragraph_format.left_indent
        > 0
    )
    assert "Example [https://example.invalid/page]" in texts
    assert "<div>raw HTML</div>" in texts
    assert r"LaTeX: \(a_b\) and $a_b$." in texts
    assert "badcharacters" in texts
    styled = next(p for p in paragraphs if p.text.startswith("bold and"))
    assert any(run.text == "bold" and run.bold for run in styled.runs)
    assert any(run.text == "italic" and run.italic for run in styled.runs)
    assert any(run.text == "strike" and run.font.strike for run in styled.runs)
    assert any(
        run.text == "inline code" and run.font.name == "Courier New"
        for run in styled.runs
    )
    assert not any(
        secret in joined
        for secret in [
            "PRIVATE",
            "THINKING",
            "FAILED BODY",
            "reasoning",
            "tokens",
            "routing",
        ]
    )


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Hello, WORLD!", "hello-world"),
        ("***", "chat"),
        ("", "chat"),
        (" A  B__C ", "a-b-c"),
        ("X" * 80, "x" * 60),
        ("猫", "chat"),
    ],
)
def test_slug(title: str, expected: str) -> None:
    assert slug(title) == expected


@pytest.mark.anyio
@pytest.mark.parametrize("failed_audit", [False, True, "off"])
async def test_export_route_and_audit(
    h: Harness, failed_audit: bool | str, caplog: pytest.LogCaptureFixture
) -> None:
    identifier = await h.conversation()
    await h.send(identifier)
    if failed_audit == "off":
        import httpx
        from conftest import SETTINGS

        from harness_api.app import create_app

        await h.client.aclose()
        h.app = create_app(SETTINGS, store=h.store, client=h.http)
        h.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.app),
            base_url="http://harness.test",
            headers={"Authorization": f"Bearer {h.token()}"},
        )
    else:
        h.publisher.fail = bool(failed_audit)
    response = await h.client.get(f"/api/conversations/{identifier}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == WORD_MIME
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="question.docx"'
    )
    assert Document(BytesIO(response.content)).paragraphs[0].text == "Question"
    if not failed_audit:
        event = next(
            event
            for topic, event in h.publisher.events
            if topic == "audit.events"
            and event["payload"]["action"] == "conversation.exported"
        )
        assert event["correlation_id"] == identifier
        assert event["payload"] == {
            "actor": "test-user",
            "action": "conversation.exported",
            "target": "docx",
            "outcome": "ok",
        }
    else:
        assert "audit_publish_failed" in [
            getattr(record, "code", "") for record in caplog.records
        ]
    assert "Question" not in caplog.text
    h.client.headers["Authorization"] = f"Bearer {h.token(sub='other-user')}"
    assert (
        await h.client.get(f"/api/conversations/{identifier}/export")
    ).status_code == 404
    assert h.store.rows[UUID(identifier)]["messages"]
