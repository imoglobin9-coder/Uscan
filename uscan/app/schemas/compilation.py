import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Item(BaseModel):
    document_id: str = Field(max_length=32)
    title: str | None = Field(default=None, max_length=200)
    pages: str = Field(default="all", max_length=200)  # "all" or "1-3,5" (1-based, among non-deleted pages)


class Options(BaseModel):
    cover: bool = True
    toc: bool = True
    separators: bool = False
    page_numbers: bool = True
    header: str = Field(default="", max_length=120)
    footer: str = Field(default="", max_length=120)
    page_size: str = Field(default="original", max_length=20)  # original|A4|LETTER|LEGAL|<w>x<h> in points
    quality: Literal["original", "optimized"] = "original"
    text_layer: bool = True

    @field_validator("page_size")
    @classmethod
    def _size(cls, v: str) -> str:
        if v in ("original", "A4", "LETTER", "LEGAL") or re.fullmatch(r"\d{2,4}(\.\d+)?x\d{2,4}(\.\d+)?", v):
            return v
        raise ValueError("Unsupported page size.")


class CompilationIn(BaseModel):
    title: str = Field(default="Compiled Report", max_length=200)
    items: list[Item] = Field(min_length=1, max_length=200)
    options: Options = Options()


def comp_out(c) -> dict:
    return {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(), "items": c.items,
            "options": c.options, "status": c.status, "page_count": c.page_count, "error": c.error,
            "download": f"/api/compilations/{c.id}/download" if c.status == "done" else None}
