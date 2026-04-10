"""
Core coding agent: observe → think → act loop.
Uses prompt-based tool calling (works with any model, no function-calling API needed).
"""

import json
import re
import os
import time
from openai import OpenAI
from typing import Optional

from .tools import (
    file_read, file_write, file_edit, bash, search_files,
    directory_tree, ToolError,
)
from .trajectory import TrajectoryLogger


SYSTEM_PROMPT = """You are a software engineer fixing a bug. You have tools to explore code and make edits.

TOOLS - use exactly ONE per response inside <tool> tags:

<tool>{"name": "bash", "args": {"command": "grep -rn 'search_term' path/"}}</tool>
<tool>{"name": "file_read", "args": {"path": "path/to/file.py"}}</tool>
<tool>{"name": "file_edit", "args": {"path": "path/to/file.py", "old_str": "exact old code", "new_str": "new code"}}</tool>
<tool>{"name": "bash", "args": {"command": "python -m pytest path/to/test.py -x"}}</tool>
<tool>{"name": "directory_tree", "args": {"path": "."}}</tool>
<tool>{"name": "submit", "args": {}}</tool>

STRICT WORKFLOW - follow this exact order:
Step 1: Run directory_tree on "." to see repo layout
Step 2: Use bash with grep to find the relevant code: grep -rn "keyword_from_issue" .
Step 3: Use file_read on the file containing the bug
Step 4: Use file_edit to fix the bug. old_str must be an EXACT copy of existing code. new_str is the replacement.
Step 5: Try to find and run tests with: find . -path "*/test*" -name "*.py" | head -20
Step 6: If you find tests, run them. If tests pass OR you cannot find tests, use submit.

CRITICAL RULES:
- NEVER read the same file twice. After reading a file, either edit it or move on.
- NEVER use search_files. Use bash with grep instead.
- Make the SMALLEST possible fix. Change only the broken line(s).
- For file_edit: old_str must match the file EXACTLY (including whitespace and indentation).
- Tests may be in a top-level tests/ directory, NOT inside the source package.
- If you cannot find test files after 2 attempts, just submit your fix.
- Do NOT modify test files.
- Do NOT spend more than 3 steps looking for tests.
"""


class CodingAgent:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        workspace: str,
        logger: TrajectoryLogger,
        max_steps: int = 30,
        temperature: float = 0.2,
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.workspace = os.path.abspath(workspace)
        self.logger = logger
        self.max_steps = max_steps
        self.temperature = temperature
        self.messages = []

    def run(self, issue_text: str) -> str:
        """Run the agent on an issue. Returns the git diff (patch)."""
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Here is the GitHub issue to fix:\n\n{issue_text}\n\n"
                    f"The repository is available in your workspace. "
                    f"Start by exploring the repo structure with directory_tree."
                ),
            },
        ]

        last_tool_key = None
        repeat_count = 0

        for step in range(1, self.max_steps + 1):
            if step > 1 and "localhost" not in self.client.base_url.host:
                time.sleep(15)  # Rate limit: only for remote APIs
            self._trim_messages(max_messages=16)
            print(f"  Step {step}/{self.max_steps}...", end=" ", flush=True)

            # Get LLM response with retry
            text = self._call_llm()
            if text is None:
                continue

            # Append assistant response
            self.messages.append({"role": "assistant", "content": text})

            # Parse tool call from response
            tool_call = self._parse_tool_call(text)
            if tool_call is None:
                print(f"thinking: {text[:80]}...")
                # Debug: show what the model tried to output
                if "<tool>" in text:
                    tool_start = text.index("<tool>")
                    print(f"    [parse failed] raw tool content: {text[tool_start:tool_start+200]}...")
                # Give the model a concrete example of the format it needs
                self.messages.append({
                    "role": "user",
                    "content": (
                        "Your tool call was not formatted correctly. "
                        "You MUST respond with valid JSON inside <tool></tool> tags. "
                        "Example for editing a file:\n"
                        '<tool>{"name": "file_edit", "args": {"path": "path/to/file.py", '
                        '"old_str": "exact line to replace", "new_str": "new line"}}</tool>\n'
                        "Example for running a command:\n"
                        '<tool>{"name": "bash", "args": {"command": "grep -rn pattern dir/"}}</tool>\n'
                        "Try again now."
                    ),
                })
                continue

            fn_name = tool_call["name"]
            fn_args = tool_call.get("args", {})

            # Loop detection: if same tool+args repeated 3 times, nudge the model
            tool_key = json.dumps({"name": fn_name, "args": fn_args}, sort_keys=True)
            if tool_key == last_tool_key:
                repeat_count += 1
            else:
                repeat_count = 0
                last_tool_key = tool_key

            if repeat_count >= 2:
                print(f"(loop detected, redirecting)")
                if fn_name == "file_edit":
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your file_edit failed because old_str appears MORE THAN ONCE in the file. "
                            "You must include MORE SURROUNDING LINES to make old_str unique. "
                            "For example, include the class name or decorator above the line:\n"
                            '<tool>{"name": "file_edit", "args": {"path": "file.py", '
                            '"old_str": "class ASCIIUsernameValidator(validators.RegexValidator):\\n'
                            "    regex = r'^[\\\\w.@+-]+$'\", "
                            '"new_str": "class ASCIIUsernameValidator(validators.RegexValidator):\\n'
                            "    regex = r'\\\\A[\\\\w.@+-]+\\\\Z'\"}}</tool>\n"
                            "Include enough context lines that the old_str is UNIQUE in the file."
                        ),
                    })
                else:
                    self.messages.append({
                        "role": "user",
                        "content": (
                            f"You have repeated the same action ({fn_name}) 3 times. "
                            "It's not working. Try a COMPLETELY DIFFERENT approach. "
                            "If you were searching, try a different search term. "
                            "If you were editing, include more context lines in old_str. "
                            "If you are stuck, use submit to submit what you have."
                        ),
                    })
                repeat_count = 0
                continue

            print(f"{fn_name}({self._summarize_args(fn_args)})")

            # Handle submit
            if fn_name == "submit":
                result = self._extract_patch()
                self.logger.log_step(step, fn_name, fn_args, result)
                self.logger.mark_submitted(result)
                print(f"  → Submitted! Patch is {len(result)} chars")
                return result

            # Execute tool
            result, error = self._execute_tool(fn_name, fn_args)

            # Log
            thought = text.split("<tool>")[0].strip() if "<tool>" in text else text
            self.logger.log_step(
                step, fn_name, fn_args, result,
                thought=thought[:500],
                error=error,
            )

            # Feed result back (truncated)
            truncated = result[:3000] + "\n...[truncated]" if len(result) > 3000 else result
            self.messages.append({
                "role": "user",
                "content": f"Tool result for {fn_name}:\n```\n{truncated}\n```\n\nContinue working on the issue. Use another tool.",
            })

        # Step limit reached
        print("  → Step limit reached, extracting patch...")
        patch = self._extract_patch()
        self.logger.mark_submitted(patch)
        return patch

    def _call_llm(self) -> Optional[str]:
        """Call the LLM with retries for rate limiting."""
        for attempt in range(5):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    temperature=self.temperature,
                    max_tokens=8192,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                err = str(e)
                if "rate_limit" in err.lower() or "413" in err or "429" in err:
                    wait = 20 * (attempt + 1)
                    print(f"rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"API error: {e}")
                    return None
        return None

    def _repair_json(self, s: str) -> Optional[dict]:
        """Try to parse JSON, repairing common issues from LLM output."""
        # First try direct parse
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # Fix: invalid escape sequences (\w, \d, \A, \Z, etc.) and literal newlines
        valid_escapes = set('"\\bfnrtu/')
        fixed = []
        i = 0
        in_string = False
        while i < len(s):
            ch = s[i]
            if not in_string:
                if ch == '"':
                    in_string = True
                fixed.append(ch)
                i += 1
            else:
                if ch == '\\' and i + 1 < len(s):
                    next_ch = s[i + 1]
                    if next_ch == '"':
                        # Escaped quote — keep as is
                        fixed.append('\\')
                        fixed.append('"')
                        i += 2
                    elif next_ch in valid_escapes:
                        # Valid JSON escape — keep as is
                        fixed.append('\\')
                        fixed.append(next_ch)
                        i += 2
                    else:
                        # Invalid escape like \w, \d, \A, \Z — double the backslash
                        fixed.append('\\\\')
                        fixed.append(next_ch)
                        i += 2
                elif ch == '"':
                    in_string = False
                    fixed.append(ch)
                    i += 1
                elif ch == '\n':
                    fixed.append('\\n')
                    i += 1
                elif ch == '\t':
                    fixed.append('\\t')
                    i += 1
                else:
                    fixed.append(ch)
                    i += 1

        try:
            return json.loads(''.join(fixed))
        except json.JSONDecodeError:
            pass

        return None

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        """Extract a tool call from the response. Handles nested braces and malformed output."""
        # Try <tool> tags first (greedy to capture nested braces)
        match = re.search(r"<tool>\s*(\{.*\})\s*</tool>", text, re.DOTALL)
        if match:
            result = self._repair_json(match.group(1))
            if result:
                return result

        # Fallback: <tool> without closing tag (model forgot </tool>)
        match = re.search(r"<tool>\s*(\{.*\})", text, re.DOTALL)
        if match:
            result = self._repair_json(match.group(1))
            if result:
                return result
            # Try progressively trimming from the end
            s = match.group(1).strip()
            for i in range(len(s) - 1, 0, -1):
                if s[i] == '}':
                    result = self._repair_json(s[:i+1])
                    if result:
                        return result

        # Fallback: JSON in code blocks
        match = re.search(r"```(?:json)?\s*(\{[^`]*\"name\"[^`]*\})\s*```", text, re.DOTALL)
        if match:
            result = self._repair_json(match.group(1))
            if result:
                return result

        # Fallback: brace-counting approach for nested objects
        for m in re.finditer(r'\{"name"', text):
            start = m.start()
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        result = self._repair_json(text[start:i+1])
                        if result:
                            return result
                        break

        return None

    def _execute_tool(self, name: str, args: dict) -> tuple[str, Optional[str]]:
        """Execute a tool and return (result, error)."""
        try:
            if name == "file_read":
                return file_read(args["path"], self.workspace), None
            elif name == "file_write":
                return file_write(args["path"], args["content"], self.workspace), None
            elif name == "file_edit":
                return file_edit(
                    args["path"], args["old_str"], args["new_str"], self.workspace
                ), None
            elif name == "bash":
                return bash(args["command"], self.workspace), None
            elif name == "search_files":
                return search_files(args["pattern"], self.workspace), None
            elif name == "directory_tree":
                return directory_tree(args.get("path", "."), self.workspace), None
            else:
                return f"Unknown tool: {name}", f"Unknown tool: {name}"
        except ToolError as e:
            return f"Error: {e}", str(e)
        except Exception as e:
            return f"Error: {e}", str(e)

    def _extract_patch(self) -> str:
        """Extract git diff from the workspace."""
        try:
            result = bash("git diff", self.workspace)
            if result.strip():
                return result
            result = bash("git diff --cached", self.workspace)
            return result if result.strip() else "(no changes detected)"
        except Exception:
            return "(failed to extract patch)"

    def _summarize_args(self, args: dict) -> str:
        parts = []
        for k, v in args.items():
            s = str(v)
            if len(s) > 60:
                s = s[:57] + "..."
            parts.append(f"{k}={s}")
        return ", ".join(parts)

    def _trim_messages(self, max_messages: int = 16):
        """Keep system + first user + last N messages."""
        if len(self.messages) <= max_messages + 2:
            return
        self.messages = self.messages[:2] + self.messages[-max_messages:]