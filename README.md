# SWE-bench Agent Framework for Reward Hacking Research

A framework that runs an LLM-based coding agent on SWE-bench tasks, logs full
trajectories (file reads, edits, bash commands), and evaluates both visible and
hidden test performance — designed for studying reward hacking in agentic coding.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key (supports OpenAI-compatible APIs including local vLLM/ollama)
export AGENT_API_KEY="your-key-here"
export AGENT_BASE_URL="https://api.openai.com/v1"   # or http://localhost:11434/v1 for ollama
export AGENT_MODEL="gpt-4o"                          # or local model name

# 3. Download SWE-bench Lite and pick 10 instances
python scripts/download_dataset.py

# 4. Run the agent on all selected instances
python run_all.py --config configs/default.yaml

# 5. Evaluate with SWE-bench harness (requires Docker)
python scripts/evaluate.py --predictions patches/predictions.json
```

## Project Structure

```
├── agent/
│   ├── __init__.py
│   ├── agent.py            # Core agent loop (observe → think → act)
│   ├── tools.py            # Tools: file_read, file_write, bash, search
│   ├── trajectory.py       # Trajectory logger (records every action)
│   └── exploit_detector.py # Detects reward-hacking behaviors
├── configs/
│   └── default.yaml        # Configuration (model, tools, limits)
├── scripts/
│   ├── download_dataset.py # Fetches SWE-bench Lite, picks 10 instances
│   └── evaluate.py         # Runs SWE-bench Docker evaluation
├── logs/                   # Per-instance trajectory logs (JSON)
├── patches/                # Agent-generated patches + predictions.json
├── run_all.py              # Main entry point
├── run_single.py           # Run agent on one instance
└── requirements.txt
```

## How It Works

1. **Episode setup**: Clones the repo at the correct commit, places the issue
   text in the agent's context, gives it tool access.
2. **Agent loop**: The agent reads files, edits code, runs tests, iterates up
   to a configurable step limit.
3. **Trajectory logging**: Every tool call is recorded with timestamps, enabling
   post-hoc exploit detection.
4. **Patch extraction**: After the agent finishes, a git diff is saved.
5. **Hidden evaluation**: SWE-bench's Docker harness runs gold tests on the patch.

## Reward Hacking Metrics

The trajectory logger feeds into `exploit_detector.py` which flags:
- Reading test files or evaluator scripts
- Modifying test infrastructure
- Hardcoding expected outputs
- Visible-hidden performance gap
