from prompts import system_prompt
from prompts.prompt_types import Stack
from prompts.react_native import REACT_NATIVE_SYSTEM_PROMPT


def get_system_prompt(stack: Stack) -> str:
    """The web stacks share one system prompt; React Native has its own."""
    if stack == "react_native":
        return REACT_NATIVE_SYSTEM_PROMPT
    return system_prompt.SYSTEM_PROMPT
