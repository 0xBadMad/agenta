from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import enum


class ConfigDB(BaseModel):
    config_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class Error(BaseModel):
    message: str
    stacktrace: Optional[str] = None


class Result(BaseModel):
    type: str
    value: Optional[Any] = None
    error: Optional[Error] = None


class InvokationResult(BaseModel):
    result: Result
    cost: Optional[float] = None
    latency: Optional[float] = None


class EvaluationScenarioResult(BaseModel):
    evaluator_config: str
    result: Result


class AggregatedResult(BaseModel):
    evaluator_config: str
    result: Result


class CorrectAnswer(BaseModel):
    key: str
    value: str


class EvaluationScenarioInput(BaseModel):
    name: str
    type: str
    value: str


class EvaluationScenarioOutput(BaseModel):
    result: Result
    cost: Optional[float] = None
    latency: Optional[float] = None


class HumanEvaluationScenarioInput(BaseModel):
    input_name: str
    input_value: str


class HumanEvaluationScenarioOutput(BaseModel):
    variant_id: str
    variant_output: str


class TemplateType(enum.Enum):
    IMAGE = "image"
    ZIP = "zip"


class AppType(str, enum.Enum):
    CHAT_TEMPLATE = "TEMPLATE:simple_chat"
    PROMPT_TEMPLATE = "TEMPLATE:single_prompt"
    CUSTOM = "CUSTOM"

    @classmethod
    def friendly_tag(cls, app_type: str):
        mappings = {
            cls.CHAT_TEMPLATE: "chat",
            cls.PROMPT_TEMPLATE: "completion",
            cls.CUSTOM: "custom",
        }
        return mappings.get(app_type, None)
