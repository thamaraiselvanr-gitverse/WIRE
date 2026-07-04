from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
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
    status = Column(String, default="pending")  # pending, running, completed, failed
    fidelity_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="projects")
    template = relationship("TemplateMeta", back_populates="project", uselist=False)


class TemplateMeta(Base):  # type: ignore[misc]
    __tablename__ = "templates"

    id = Column(
        String, primary_key=True
    )  # Cryptographic ID from our pipeline e.g. 13dc44d78d8e
    project_id = Column(Integer, ForeignKey("projects.id"))
    tags = Column(String, nullable=True)  # JSON string of tags
    file_path = Column(String, nullable=False)

    project = relationship("Project", back_populates="template")
