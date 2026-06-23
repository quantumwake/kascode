"""Protocol test: drive the server with the official anthropic SDK over an
in-process ASGI transport, using a fake engine (no model weights needed).

Run:  uv run python tests/test_api.py
"""

import asyncio
import sys

import anthropic
import httpx

sys.path.insert(0, ".")

import server.app as app_module
from server.engine import GenChunk

CANNED = (
    "<|channel>thought\nUser asked about weather; call the tool.\n<channel|>"
    "Let me check.\n\n"
    '<|tool_call>call:get_weather{city:<|"|>Paris<|"|>}<tool_call|>'
)


from server.prompting import GemmaDialect


class FakeEngine:
    model_id = "fake"
    dialect = GemmaDialect()

    def tokenize(self, chat, tools=None, enable_thinking=False):
        # Tools must arrive via the native template payload, not prompt text.
        assert tools and tools[0]["function"]["name"] == "get_weather", tools
        return list(range(42))

    def generate(self, prompt_tokens, **kw):
        # Emit in awkward chunk boundaries to exercise the holdback logic.
        text = CANNED
        for i in range(0, len(text), 7):
            yield GenChunk(text=text[i : i + 7])
        yield GenChunk(
            text="", done=True, prompt_tokens=42, generation_tokens=33, finish_reason="stop"
        )

    def request_cancel(self):
        return False  # no job active in this synchronous fake


async def main() -> None:
    app_module.engine = FakeEngine()
    transport = httpx.ASGITransport(app=app_module.app)
    client = anthropic.AsyncAnthropic(
        base_url="http://test",
        api_key="local",
        http_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
    )
    kwargs = dict(
        model="fake",
        max_tokens=256,
        tools=[
            {
                "name": "get_weather",
                "description": "Get weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        messages=[{"role": "user", "content": "Weather in Paris?"}],
    )

    # --- non-streaming ---
    resp = await client.messages.create(**kwargs)
    assert resp.stop_reason == "tool_use", resp.stop_reason
    assert resp.content[0].type == "thinking" and "weather" in resp.content[0].thinking
    assert resp.content[1].type == "text" and resp.content[1].text == "Let me check."
    tool = resp.content[2]
    assert tool.type == "tool_use" and tool.name == "get_weather"
    assert tool.input == {"city": "Paris"}, tool.input
    assert resp.usage.input_tokens == 42 and resp.usage.output_tokens == 33
    print("non-streaming: OK")

    # --- streaming (SDK accumulator must rebuild the same message) ---
    async with client.messages.stream(**kwargs) as stream:
        deltas = [t async for t in stream.text_stream]
        final = await stream.get_final_message()
    assert "".join(deltas).strip() == "Let me check."
    assert final.stop_reason == "tool_use"
    tool = next(b for b in final.content if b.type == "tool_use")
    assert tool.name == "get_weather" and tool.input == {"city": "Paris"}
    print("streaming: OK")

    # --- /v1/cancel is wired and returns the active-job flag ---
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as hc:
        body = (await hc.post("/v1/cancel")).json()
    assert body["ok"] is True and body["active"] is False, body
    print("cancel endpoint: OK")

    # --- validation errors use the Anthropic error envelope ---
    try:
        await client.messages.create(model="fake", max_tokens=10, messages=[])
        raise AssertionError("expected BadRequestError")
    except anthropic.BadRequestError:
        print("error envelope: OK")


if __name__ == "__main__":
    asyncio.run(main())
