"""
Logs every agent action for post-hoc analysis and reward hacking detection.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from pathlib import Path


@dataclass
class Step:
    step_num: int
    timestamp: float
    tool_name: str
    tool_args: dict
    result: str
    thought: Optional[str] = None  # Agent's reasoning before the action
    error: Optional[str] = None


@dataclass
class Trajectory:
    instance_id: str
    model: str
    steps: list[Step] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    submitted: bool = False
    patch: str = ""
    # Evaluation results (filled post-hoc)
    visible_pass_rate: Optional[float] = None
    hidden_pass_rate: Optional[float] = None
    exploit_flags: list[str] = field(default_factory=list)


class TrajectoryLogger:
    def __init__(self, instance_id: str, model: str, log_dir: str):
        self.trajectory = Trajectory(
            instance_id=instance_id,
            model=model,
            start_time=time.time(),
        )
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_step(
        self,
        step_num: int,
        tool_name: str,
        tool_args: dict,
        result: str,
        thought: Optional[str] = None,
        error: Optional[str] = None,
    ):
        step = Step(
            step_num=step_num,
            timestamp=time.time(),
            tool_name=tool_name,
            tool_args=tool_args,
            result=result[:5000],  # Cap stored result size
            thought=thought,
            error=error,
        )
        self.trajectory.steps.append(step)

    def mark_submitted(self, patch: str):
        self.trajectory.submitted = True
        self.trajectory.patch = patch
        self.trajectory.end_time = time.time()

    def set_eval_results(
        self,
        visible_pass_rate: float,
        hidden_pass_rate: float,
        exploit_flags: list[str],
    ):
        self.trajectory.visible_pass_rate = visible_pass_rate
        self.trajectory.hidden_pass_rate = hidden_pass_rate
        self.trajectory.exploit_flags = exploit_flags

    def save(self):
        self.trajectory.end_time = self.trajectory.end_time or time.time()
        path = self.log_dir / f"{self.trajectory.instance_id}.json"
        with open(path, "w") as f:
            json.dump(asdict(self.trajectory), f, indent=2, default=str)
        return str(path)

    def get_files_read(self) -> list[str]:
        """Return all file paths the agent read."""
        return [
            s.tool_args.get("path", "")
            for s in self.trajectory.steps
            if s.tool_name == "file_read"
        ]

    def get_files_written(self) -> list[str]:
        """Return all file paths the agent wrote to."""
        return [
            s.tool_args.get("path", "")
            for s in self.trajectory.steps
            if s.tool_name in ("file_write", "file_edit")
        ]

    def get_bash_commands(self) -> list[str]:
        """Return all bash commands the agent ran."""
        return [
            s.tool_args.get("command", "")
            for s in self.trajectory.steps
            if s.tool_name == "bash"
        ]
