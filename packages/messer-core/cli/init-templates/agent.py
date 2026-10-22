"""{{name}} — Messer agent created with `messer create`. Edit freely: the Messer Studio keeps this code and its
configuration in sync while the code only uses these patterns; otherwise the code is the source of truth.
Run it locally with `messer start` and publish it with `messer push` + `messer deploy`."""

from messer import Agent

SYSTEM_PROMPT = "Eres un asistente útil y preciso. Responde en el idioma del usuario."

agent = Agent(
    name="{{name}}",
    description="",
    model="{{model}}",
    system_prompt=SYSTEM_PROMPT,
    max_tokens=4096,
    max_iter=10,
    timeout=120,
    tools=[],
)
