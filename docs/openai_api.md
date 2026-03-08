# OpenAI API Reference

## Latest Models (March 2026)

### Reasoning Models
| Model | Description | Use Case |
|-------|-------------|----------|
| `gpt-5.4` | Most capable reasoning model | Complex analysis, predictions |
| `gpt-5.4-pro` | Extended thinking version | Deep research |
| `gpt-5` | Strong reasoning | General purpose |
| `gpt-5-mini` | Fast, cost-efficient reasoning | Agents, coordination |
| `gpt-5-nano` | Cheapest reasoning | Simple tasks |

### Non-Reasoning Models
| Model | Description | Use Case |
|-------|-------------|----------|
| `gpt-4.1` | Smartest non-reasoning | Code, instruction following |
| `gpt-4.1-mini` | Fast non-reasoning | Quick tasks |
| `gpt-4.1-nano` | Cheapest non-reasoning | Bulk processing |
| `gpt-4o` | Previous gen multimodal | Legacy support |
| `gpt-4o-mini` | Previous gen fast | Legacy support |

## This Project's Model Choices
- **Orchestrator**: `gpt-5-mini` - coordinates agents efficiently
- **Stats Agent**: `gpt-5-mini` - analyzes statistical data
- **News Agent**: `gpt-5-mini` + WebSearchTool - searches and synthesizes news
- **Prediction Agent**: `gpt-5.4` - highest-value step, needs best reasoning

## Responses API
The Responses API is the new standard (replaces Chat Completions for new projects).
Used internally by the Agents SDK.

## Web Search Tool
Available as a built-in tool in the Agents SDK:
```python
from agents.tool import WebSearchTool

agent = Agent(
    tools=[WebSearchTool()],
    ...
)
```
The agent can then search the web in real-time during its execution.

## Structured Outputs
Use Pydantic models with the Agents SDK:
```python
from pydantic import BaseModel

class Result(BaseModel):
    answer: str
    confidence: float

agent = Agent(output_type=Result, ...)
```
