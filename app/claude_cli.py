"""Runs the Claude Code CLI headless (`claude -p`) using the server's Claude subscription.

Auth: set CLAUDE_CODE_OAUTH_TOKEN (made with `claude setup-token` on the server).
"""
import asyncio
import json
import logging
import re

from . import config

log = logging.getLogger(__name__)
_sem = asyncio.Semaphore(config.CLAUDE_CONCURRENCY)


class ClaudeError(Exception):
    pass


async def ask(
    prompt: str,
    *,
    model: str,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
    max_turns: int = 4,
) -> str:
    args = [
        config.CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(max_turns),
    ]
    if allowed_tools:
        args += ["--allowedTools", ",".join(allowed_tools)]

    async with _sem:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            # Prompt goes through stdin so long data never hits argv limits.
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), config.CLAUDE_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeError(f"Claude ไม่ตอบภายใน {config.CLAUDE_TIMEOUT} วินาที")

    if proc.returncode != 0 and not out:
        raise ClaudeError(f"claude exited {proc.returncode}: {err.decode(errors='replace')[-500:]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise ClaudeError(f"อ่านผลจาก claude ไม่ได้: {out[:300]!r}")
    if data.get("is_error"):
        raise ClaudeError(str(data.get("result") or data.get("subtype") or "unknown error"))
    log.info("claude %s cost=%s turns=%s", model, data.get("total_cost_usd"), data.get("num_turns"))
    return data.get("result") or ""


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a reply (tolerates ```json fences and extra prose)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            raise ClaudeError(f"ไม่พบ JSON ในคำตอบ: {text[:200]!r}")
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
    if candidate is None:
        raise ClaudeError(f"JSON ไม่สมบูรณ์: {text[:200]!r}")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"JSON ผิดรูปแบบ: {e}") from e
