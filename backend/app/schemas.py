"""Formatos de entrada da API (validados pelo Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool, StrictStr, field_validator

Category = Literal["cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler"]

MAX_CENTS = 100_000_000  # R$ 1 milhão: qualquer coisa acima disso é erro de coleta


class IngestItem(BaseModel):
    store: str = Field(min_length=1, max_length=40)
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)
    category: Category
    brand: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    specs: dict = Field(default_factory=dict)
    image_url: HttpUrl | None = None
    condition: Literal["new", "used"] = "new"
    seller: str | None = Field(default=None, max_length=120)
    price_cash: int = Field(gt=0, lt=MAX_CENTS, description="à vista/PIX, em centavos")
    price_installment: int | None = Field(default=None, gt=0, lt=MAX_CENTS)
    in_stock: bool

    @field_validator("image_url")
    @classmethod
    def _image_https(cls, v):
        if v is not None and v.scheme != "https":
            raise ValueError("image_url precisa ser https://")
        return v


class IngestBatch(BaseModel):
    collected_at: datetime | None = None
    items: list[IngestItem] = Field(min_length=1, max_length=2000)


class BuildItemUpdate(BaseModel):
    part_id: int | None = Field(default=None, gt=0)


class ChannelAdd(BaseModel):
    """`@nome`, `nome`, `https://t.me/nome` ou `t.me/s/nome` (normalizado em app/tg/channels.py)."""
    model_config = ConfigDict(extra="forbid")
    handle: StrictStr = Field(min_length=1, max_length=200)


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
