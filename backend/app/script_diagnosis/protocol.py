from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CHARACTERS = 100_000
EXTENSIONS = (".txt", ".md", ".markdown", ".docx", ".pdf")
DIMENSIONS = {
    "duration": "总时长预估", "novelty": "新颖度评估", "pacing": "节奏把控评估",
    "emotion": "情绪浓度评估", "risk": "风险合规评估",
}
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
DimensionKey = Literal["duration", "novelty", "pacing", "emotion", "risk"]


class SourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="来源文件名或粘贴正文名称。")
    text: str = Field(min_length=1, max_length=MAX_CHARACTERS, description="待诊断的完整剧本正文，最多十万字符。")


class DiagnosisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: str = Field(min_length=8, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$", description="当前账号内唯一的幂等提交键；相同键返回同一诊断。")
    title: str = Field(default="剧本诊断", min_length=1, max_length=255, description="剧本名称，用于报告和历史记录。")
    sources: list[SourceInput] = Field(default_factory=list, max_length=MAX_FILES, description="按合并顺序排列的剧本来源，与项目文档引用互斥。")
    project_id: str | None = Field(default=None, max_length=96, description="可选来源工程 ID，必须与文档 ID 同时提供。")
    document_id: str | None = Field(default=None, max_length=96, description="来源工程中的剧本文档 ID；服务端读取正文快照。")

    @model_validator(mode="after")
    def exclusive_input(self):
        if self.document_id:
            if not self.project_id or self.sources:
                raise ValueError("项目文档需要同时指定项目，且不能混入上传正文")
        elif not self.sources or self.project_id:
            raise ValueError("请提交剧本正文，或选择项目中的文档")
        return self


class Evidence(BaseModel):
    source_id: str = Field(min_length=1, max_length=32)
    block_id: str = Field(min_length=1, max_length=48)
    quote: str = Field(min_length=1, max_length=400)
    start: int = 0
    end: int = 0


class Finding(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    priority: Literal["high", "medium", "low"]
    explanation: str = Field(min_length=1, max_length=800)
    suggestion: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(min_length=1, max_length=3)


class Dimension(BaseModel):
    key: DimensionKey
    conclusion: str = Field(min_length=1, max_length=600)
    strengths: list[str] = Field(default_factory=list, max_length=3)
    issues: list[Finding] = Field(default_factory=list, max_length=3)


class DurationRange(BaseModel):
    min_seconds: float = Field(ge=0, allow_inf_nan=False)
    max_seconds: float = Field(ge=0, allow_inf_nan=False)
    basis: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def ordered(self):
        if self.max_seconds < self.min_seconds:
            raise ValueError("时长上限不能小于下限")
        return self


class SegmentReport(BaseModel):
    summary: str = Field(min_length=1, max_length=800)
    duration: DurationRange
    dimensions: list[Dimension] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def all_dimensions(self):
        if {item.key for item in self.dimensions} != set(DIMENSIONS):
            raise ValueError("必须包含且仅包含五项诊断维度")
        self.dimensions.sort(key=lambda item: list(DIMENSIONS).index(item.key))
        return self
