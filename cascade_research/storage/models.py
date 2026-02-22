"""
SQLAlchemy ORM Models for cascade-research

Declarative models for the 7 standard tables. Virtual tables (FTS5, sqlite-vec)
are handled separately in virtual_tables.py since they have no ORM equivalent.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class KB(Base):
    __tablename__ = "kb"

    name = Column(String, primary_key=True)
    kb_type = Column(String, nullable=False)
    path = Column(String, nullable=False)
    description = Column(Text)
    last_indexed = Column(String)
    entry_count = Column(Integer, default=0)

    entries = relationship("Entry", back_populates="kb_rel", cascade="all, delete-orphan")


class Entry(Base):
    __tablename__ = "entry"

    id = Column(String, primary_key=True)
    kb_name = Column(
        String, ForeignKey("kb.name", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    entry_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text)
    summary = Column(Text)
    file_path = Column(String)

    # Event-specific fields
    date = Column(String)
    importance = Column(Integer)
    status = Column(String)
    location = Column(String)

    # Research-specific fields
    research_status = Column(String)
    role = Column(String)
    era = Column(String)

    # Timestamps
    created_at = Column(String)
    updated_at = Column(String)
    indexed_at = Column(String, server_default="CURRENT_TIMESTAMP")

    # Relationships
    kb_rel = relationship("KB", back_populates="entries")
    tags = relationship("EntryTag", back_populates="entry", cascade="all, delete-orphan")
    actors = relationship("EntryActor", back_populates="entry", cascade="all, delete-orphan")
    sources = relationship("Source", back_populates="entry", cascade="all, delete-orphan")
    outgoing_links = relationship(
        "Link", back_populates="source_entry", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tag"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)

    entry_tags = relationship("EntryTag", back_populates="tag")


class EntryTag(Base):
    __tablename__ = "entry_tag"

    entry_id = Column(String, nullable=False, primary_key=True)
    kb_name = Column(String, nullable=False, primary_key=True)
    tag_id = Column(
        Integer, ForeignKey("tag.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "kb_name"],
            ["entry.id", "entry.kb_name"],
            ondelete="CASCADE",
        ),
        Index("idx_entry_tag_entry", "entry_id", "kb_name"),
        Index("idx_entry_tag_tag", "tag_id"),
    )

    entry = relationship("Entry", back_populates="tags")
    tag = relationship("Tag", back_populates="entry_tags")


class EntryActor(Base):
    __tablename__ = "entry_actor"

    entry_id = Column(String, nullable=False, primary_key=True)
    kb_name = Column(String, nullable=False, primary_key=True)
    actor_name = Column(String, nullable=False, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "kb_name"],
            ["entry.id", "entry.kb_name"],
            ondelete="CASCADE",
        ),
        Index("idx_entry_actor_actor", "actor_name"),
    )

    entry = relationship("Entry", back_populates="actors")


class Link(Base):
    __tablename__ = "link"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String, nullable=False)
    source_kb = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    target_kb = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    inverse_relation = Column(String, nullable=False)
    note = Column(Text)
    created_at = Column(String, server_default="CURRENT_TIMESTAMP")

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_kb"],
            ["entry.id", "entry.kb_name"],
            ondelete="CASCADE",
        ),
        Index("idx_link_source", "source_id", "source_kb"),
        Index("idx_link_target", "target_id", "target_kb"),
        Index("idx_link_relation", "relation"),
    )

    source_entry = relationship("Entry", back_populates="outgoing_links")


class Source(Base):
    __tablename__ = "source"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(String, nullable=False)
    kb_name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    url = Column(String)
    outlet = Column(String)
    date = Column(String)
    verified = Column(Integer, default=0)

    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "kb_name"],
            ["entry.id", "entry.kb_name"],
            ondelete="CASCADE",
        ),
        Index("idx_source_entry", "entry_id", "kb_name"),
        Index("idx_source_url", "url"),
    )

    entry = relationship("Entry", back_populates="sources")
