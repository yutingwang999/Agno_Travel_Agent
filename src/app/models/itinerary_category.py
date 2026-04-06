from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.models.base import Base

EMBEDDING_DIMENSIONS = 768


class ItineraryCategory(Base):
    __tablename__ = "itinerary_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(100), nullable=False)
    constraints: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_vector: Mapped[list] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
