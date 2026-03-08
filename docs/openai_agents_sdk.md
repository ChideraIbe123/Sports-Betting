# OpenAI Agents SDK Reference

## Installation
```bash
pip install openai-agents
```

## Core Imports
```python
from agents import Agent, Runner, function_tool
from agents.tool import WebSearchTool
```

## Agent Creation
```python
agent = Agent(
    name="My Agent",
    model="gpt-5-mini",
    instructions="You are a helpful assistant.",
    tools=[my_tool],
)
```

## function_tool Decorator
All tools must return strings. Wrap return values in `json.dumps()` for structured data.
```python
@function_tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return json.dumps({"temp": 72, "condition": "sunny"})
```

## Running Agents
```python
# Async
result = await Runner.run(agent, "Hello")
print(result.final_output)

# Sync
result = Runner.run_sync(agent, "Hello")
print(result.final_output)
```

## Agent.as_tool()
Convert an agent into a tool that another agent can call:
```python
stats_agent = Agent(name="Stats", ...)
news_agent = Agent(name="News", ...)

orchestrator = Agent(
    name="Orchestrator",
    tools=[
        stats_agent.as_tool(
            tool_name="get_stats",
            tool_description="Get player statistics and matchup data"
        ),
        news_agent.as_tool(
            tool_name="get_news",
            tool_description="Get recent news and injury reports"
        ),
    ],
)
```

## WebSearchTool (Built-in)
Gives an agent real-time web search capability:
```python
from agents.tool import WebSearchTool

news_agent = Agent(
    name="News Agent",
    model="gpt-5-mini",
    tools=[WebSearchTool()],
    instructions="Search the web for recent news..."
)
```

## Structured Output (Pydantic)
```python
from pydantic import BaseModel

class Prediction(BaseModel):
    result: str
    confidence: float
    reasoning: str

agent = Agent(
    name="Predictor",
    model="gpt-5.4",
    output_type=Prediction,
    instructions="Analyze and predict..."
)

result = Runner.run_sync(agent, "Predict X")
prediction = result.final_output  # This is a Prediction instance
print(prediction.result)
```

## Multi-Agent Pattern (This Project)
```
Orchestrator (gpt-5-mini)
  ├── Stats Agent (as_tool) → gpt-5-mini + function_tools
  ├── News Agent (as_tool) → gpt-5-mini + WebSearchTool + function_tools
  └── Prediction Agent (as_tool) → gpt-5.4 + structured output
```

## Key Rules
1. `function_tool` functions MUST return `str`
2. Use `json.dumps()` for structured return data
3. Wrap tool logic in try/except, return error strings on failure
4. `Runner.run()` is async, `Runner.run_sync()` is sync
5. `output_type` enables structured Pydantic output
