import agenta as ag
from agenta import FloatParam, MessagesInput, MultipleChoiceParam
from openai import OpenAI

client = OpenAI()

SYSTEM_PROMPT = "You have expertise in offering technical ideas to startups."
CHAT_LLM_GPT = [
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-0301",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-16k-0613",
    "gpt-4",
]

ag.init(app_name="technical_ideas", base_name="app")
ag.config.default(
    temperature=FloatParam(0.2),
    model=MultipleChoiceParam("gpt-3.5-turbo", CHAT_LLM_GPT),
)


@ag.entrypoint
def chat(
    inputs: MessagesInput = MessagesInput(
        [{"role": "system", "content": SYSTEM_PROMPT}]
    ),
) -> str:
    messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in inputs
    ]
    chat_completion = client.chat.completions.create(
        model=ag.config.model, messages=messages, temperature=ag.config.temperature
    )
    return chat_completion.choices[0].message.content
