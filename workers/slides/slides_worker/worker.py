# SPDX-License-Identifier: AGPL-3.0-only
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

import httpx
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from pydantic import BaseModel, ConfigDict, Field
from referencing import Registry, Resource

from .config import Settings
from .tracing import annotate_event, audit_context

NAMESPACE = UUID("6f1d5b7e-3c1a-4b8e-9a52-1f0c8f3e2d10")
MAX_POLL_INTERVAL_MS = 7_400_000
MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
FOLDER = Path(__file__).parent
INPUT = json.loads((FOLDER / "schemas/input.json").read_text())
TOKENS = json.loads((FOLDER / "tokens.json").read_text())
PROMPT = (
    'Return only JSON: {"title": string, "subtitle": string, '
    '"slides": [{"title": string, "bullets": [string]}]}. '
    "Include 3 to 12 content slides, with 1 to 6 bullet strings each. "
    "Use the topic and notes as content guidance."
)


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1)
    bullets: list[str] = Field(min_length=1, max_length=6)


class Deck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1)
    subtitle: str
    slides: list[Slide] = Field(min_length=3, max_length=12)


class Publisher(Protocol):
    def publish(self, topic: str, event: dict[str, Any]) -> None: ...


class Model(Protocol):
    def call(self, event: dict[str, Any], correction: str | None) -> str: ...


def envelope(
    kind: str, incoming: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    suffix = payload.get("status", payload.get("outcome", ""))
    if kind == "audit.event":
        payload = {**payload, **audit_context()}
    return {
        "event_id": str(uuid5(NAMESPACE, incoming["event_id"] + kind + suffix)),
        "type": kind,
        "version": 1,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "producer": "slides-worker",
        "user_id": incoming["user_id"],
        "correlation_id": incoming["correlation_id"],
        "payload": payload,
    }


def event_validator() -> Draft202012Validator:
    folder = FOLDER / "schemas"
    registry = Registry().with_resources(
        ("payloads/" + path.name, Resource.from_contents(json.loads(path.read_text())))
        for path in (folder / "payloads").glob("*.json")
    )
    return Draft202012Validator(
        json.loads((folder / "envelope.schema.json").read_text()),
        registry=registry,
        format_checker=FormatChecker(),
    )


class Gateway:
    def __init__(self, settings: Settings, client: httpx.Client) -> None:
        self.settings, self.client = settings, client
        self.token = ""
        self.expires_at = 0.0

    def headers(self) -> dict[str, str]:
        if time.monotonic() >= self.expires_at:
            response = self.client.post(
                self.settings.issuer + "/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                },
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
            self.token = body["access_token"]
            self.expires_at = time.monotonic() + max(0, body["expires_in"] - 30)
        return {"Authorization": "Bearer " + self.token}

    def call(self, event: dict[str, Any], correction: str | None) -> str:
        messages = [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(event["payload"]["input"])},
        ]
        if correction:
            messages.append(
                {"role": "user", "content": "Correct the JSON: " + correction}
            )
        response = self.client.post(
            self.settings.gateway_url + "/v1/call",
            headers={**self.headers(), "X-Correlation-Id": event["correlation_id"]},
            json={
                "purpose": self.settings.purpose,
                "tier": self.settings.tier,
                "user_id": event["user_id"],
                "messages": messages,
                "tools": [],
                "stream": False,
            },
            timeout=httpx.Timeout(10, read=910),
        )
        response.raise_for_status()
        content = response.json()["content"]
        if not isinstance(content, str):
            raise ValueError("gateway_shape")
        return content


def colour(name: str) -> RGBColor:
    values = TOKENS["color"]["tokens"]
    token = next(item for item in values if item["name"] == name)
    return RGBColor.from_string(token["value"]["dark"].lstrip("#"))


def build(deck: Deck, target: Path) -> None:
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(13.333333), Inches(7.5)
    title = presentation.slides.add_slide(presentation.slide_layouts[0])
    title.shapes.title.text = deck.title
    title.placeholders[1].text = deck.subtitle
    for item in deck.slides:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = item.title
        frame = slide.placeholders[1].text_frame
        frame.text = item.bullets[0]
        for bullet in item.bullets[1:]:
            frame.add_paragraph().text = bullet
    for slide in presentation.slides:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = colour("ground")
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                paragraph.font.name = "Arial"
                paragraph.font.size = Pt(32 if shape == slide.shapes.title else 22)
                paragraph.font.color.rgb = colour(
                    "phosphor" if shape == slide.shapes.title else "ink"
                )
    presentation.save(str(target))


class Worker:
    def __init__(
        self,
        root: str,
        gateway: Model,
        publisher: Publisher,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root, self.gateway, self.publisher, self.sleep = (
            Path(root),
            gateway,
            publisher,
            sleep,
        )
        (self.root / "outputs/slides").mkdir(parents=True, exist_ok=True, mode=0o755)
        self.schema = event_validator()

    def result(
        self,
        event: dict[str, Any],
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        status = "failed" if error else "completed"
        self.publisher.publish(
            "skill.results",
            envelope(
                "skill.result",
                event,
                {
                    "skill": event["payload"]["skill"],
                    "status": status,
                    "output": output,
                    "error": {
                        "code": error,
                        "message": {
                            "bad_input": "The skill input is invalid.",
                            "unknown_skill": "Unknown skill.",
                            "bad_model_output": (
                                "The model did not return valid slides."
                            ),
                            "worker_gave_up": (
                                "The presentation could not be made. Try again."
                            ),
                        }[error],
                    }
                    if error
                    else None,
                },
            ),
        )
        self.publisher.publish(
            "audit.events",
            envelope(
                "audit.event",
                event,
                {
                    "actor": "slides-worker",
                    "action": "skill.result",
                    "target": "slides",
                    "outcome": status,
                },
            ),
        )

    def handle(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        if payload["skill"] != "slides":
            self.result(event, error="unknown_skill")
            return
        if not Draft202012Validator(INPUT).is_valid(payload["input"]):
            self.result(event, error="bad_input")
            return
        identifier = str(UUID(event["correlation_id"]))
        folder = self.root / "outputs/slides" / identifier
        folder.mkdir(mode=0o755, exist_ok=True)
        finished = sorted(folder.glob("*.pptx"))
        if finished:
            path = finished[0]
            presentation = Presentation(str(path))
            title = presentation.slides[0].shapes.title.text
            count = len(presentation.slides)
        else:
            correction = None
            for attempt in range(2):
                text = self.gateway.call(event, correction)
                try:
                    lines = text.strip().splitlines()
                    if (
                        len(lines) >= 3
                        and lines[0].strip().lower() in {"```", "```json"}
                        and lines[-1].strip() == "```"
                    ):
                        text = "\n".join(lines[1:-1]).strip()
                    deck = Deck.model_validate_json(text)
                    break
                except ValueError:
                    correction = (
                        "Expected title, subtitle and 3–12 slides "
                        "with titles and 1–6 bullets."
                    )
                    if attempt == 1:
                        self.result(event, error="bad_model_output")
                        return
            slug = (
                re.sub(r"[^a-z0-9]+", "-", deck.title.lower())
                .strip("-")[:60]
                .rstrip("-")
                or "presentation"
            )
            path = folder / (slug + ".pptx")
            temporary = folder / (slug + ".tmp")
            build(deck, temporary)
            temporary.replace(path)
            title, count = deck.title, len(deck.slides) + 1
        self.result(
            event,
            {
                "file_key": str(path.relative_to(self.root)),
                "mime": MIME,
                "summary": f"{count} slides: {title}",
            },
        )

    def dead_letter(self, raw: str, event: Any, code: str) -> None:
        source = event if isinstance(event, dict) else {}
        try:
            correlation = str(UUID(source.get("correlation_id", "")))
        except ValueError, TypeError, AttributeError:
            correlation = str(uuid4())
        source = {
            "event_id": str(source.get("event_id", uuid4())),
            "correlation_id": correlation,
            "user_id": source["user_id"]
            if isinstance(source.get("user_id"), str) and source["user_id"]
            else "system",
        }
        self.publisher.publish(
            "dlq.skill.requests.slides",
            envelope(
                "dlq.entry",
                source,
                {
                    "original_message": raw,
                    "error": {
                        "code": code,
                        "message": "The presentation request could not be handled.",
                    },
                },
            ),
        )

    def process(self, raw: str) -> None:
        event: Any = {}
        try:
            event = json.loads(raw)
            self.schema.validate(event)
            annotate_event(event, job=True)
            if event["type"] != "skill.requested":
                raise ValueError("wrong_type")
        except ValueError, ValidationError:
            self.dead_letter(raw, event, "bad_message")
            return
        for attempt in range(4):
            try:
                self.handle(event)
                return
            except Exception:
                if attempt < 3:
                    self.sleep((1, 5, 15)[attempt])
                else:
                    self.dead_letter(raw, event, "worker_gave_up")
                    self.result(event, error="worker_gave_up")
