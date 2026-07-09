from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):  # type: ignore[misc]
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    projects = relationship("Project", back_populates="owner")


class Project(Base):  # type: ignore[misc]
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True, nullable=False)
    # Output-directory name for this project's run (``project_<id>``), set at
    # enqueue time. Isolates artifacts per project: two users reconstructing
    # the same domain must never share a run directory. Nullable only for
    # rows created before this column existed (legacy domain-named runs).
    run_id = Column(String(64), nullable=True)
    status = Column(String, default="pending")  # pending, running, completed, failed
    fidelity_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="projects")
    template = relationship("TemplateMeta", back_populates="project", uselist=False)


class ReconstructionJob(Base):  # type: ignore[misc]
    """A durable, persisted unit of reconstruction work.

    Replaces fire-and-forget background tasks: jobs survive restarts, can be
    claimed by a worker, and are retried on failure until ``max_attempts``.
    """

    __tablename__ = "reconstruction_jobs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    # pending -> running -> completed | failed  (failed only after max_attempts)
    status = Column(String, default="pending", index=True, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TemplateMeta(Base):  # type: ignore[misc]
    __tablename__ = "templates"

    id = Column(
        String, primary_key=True
    )  # Cryptographic ID from our pipeline e.g. 13dc44d78d8e
    project_id = Column(Integer, ForeignKey("projects.id"))
    tags = Column(String, nullable=True)  # JSON string of tags
    file_path = Column(String, nullable=False)

    project = relationship("Project", back_populates="template")
