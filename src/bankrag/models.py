"""Pydantic models for the data that crosses a boundary: cache files, the parser process, the eval set and the API.

Every page cache line, chunk file line and eval question is parsed into one of these before it travels further, so
nothing untyped moves past the function that read it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from bankrag.config import USD_TO_DKK, Bank, bank_name

BlockKind = Literal["text", "table"]
Language = Literal["en", "da"]
Category = Literal["lookup", "compare_years", "compare_banks", "why", "danish", "unanswerable"]


class Block(BaseModel):
    """One paragraph or one table from a page. Tables are rows of cells separated by "|"."""

    kind: BlockKind
    text: str


class Page(BaseModel):
    """One parsed PDF page, with the place in the report it comes from.

    `page` is the 1-based PDF page number, the page a PDF viewer jumps to. Printed page labels differ in some
    reports (Nordea's are one lower).
    """

    bank: Bank
    year: int
    page: int
    section: str
    heading: str
    blocks: list[Block] = Field(default_factory=list)
    part: str = ""


class Chunk(BaseModel):
    """A retrieval unit: a few paragraphs or one table, always from a single page."""

    id: str
    bank: Bank
    year: int
    page: int
    section: str
    heading: str
    text: str = Field(description="The body with a context line in front, as indexed for search.")
    body: str = Field(description="The page text alone, as passed to the answer model.")
    has_table: bool


class Question(BaseModel):
    """One eval question with its gold answer and the pages that support it."""

    id: str
    question: str
    lang: Language
    category: Category
    answerable: bool
    gold_answer: str
    numbers: list[list[float]] = Field(default_factory=list)
    evidence: list[list[str]] = Field(default_factory=list)
    verified: bool = False


class Source(BaseModel):
    """A page cited in an answer, numbered in the order it is first cited."""

    n: int
    chunk_id: str
    bank: Bank
    year: int
    page: int
    section: str
    cited_text: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        """Human-readable reference, for example "Nordea, Annual Report 2025, p. 40"."""
        return f"{bank_name(self.bank)}, Annual Report {self.year}, p. {self.page}"


class Answer(BaseModel):
    """An answer with its sources, token use, cost and latency."""

    question: str
    text: str
    thinking: str = Field(default="", description="Claude's summary of its reasoning before answering.")
    sources: list[Source]
    refused: bool
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_s: float
    retrieved: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_dkk(self) -> float:
        """Cost in Danish kroner at the fixed exchange rate in the config."""
        return self.cost_usd * USD_TO_DKK


class Verdict(BaseModel):
    """The LLM judge's grading of one answer against the gold answer, by the rubric in evals/judge_rubric.md.

    The field descriptions are part of the JSON schema the judge fills in. `reason` comes first so the judge explains
    before it decides.
    """

    reason: str = Field(description="One or two sentences on what is wrong with the answer, or why it passes.")
    correct: bool = Field(description="Every figure and claim that the gold answer also covers agrees with it.")
    complete: bool = Field(description="The answer gives everything the question asks for.")
    consistent: bool = Field(description="The answer does not contradict itself.")

    @property
    def passed(self) -> bool:
        """True when the answer meets all three criteria."""
        return self.correct and self.complete and self.consistent
