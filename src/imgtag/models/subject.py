"""Subject memory models.

用于主体记忆与图片主体纠正流程：
- subjects: 主体词典
- subject_samples: 主体样本向量
- image_subjects: 图片主体识别/人工纠正结果
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from imgtag.models.image import Image
    from imgtag.models.tag import Tag
    from imgtag.models.user import User


class Subject(Base, TimestampMixin):
    """主体词典。"""

    __tablename__ = "subjects"
    __table_args__ = (
        Index("ix_subjects_active", "is_active"),
        Index("ix_subjects_category_tag", "category_tag_id"),
        Index("uq_subjects_primary_tag", "primary_tag_id", unique=True),
        {"comment": "主体词典表"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, comment="主体名称")
    aliases: Mapped[Optional[list[str]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="别名列表",
    )
    alias_tag_ids: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(Integer),
        nullable=True,
        comment="主体别名标签ID列表(level=2)",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述")
    recognition_notes: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    definition_revision: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
        comment="是否启用",
    )
    category_tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tags.id", ondelete="RESTRICT"),
        nullable=False,
        comment="归属一级分类标签ID(level=0)",
    )
    primary_tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tags.id", ondelete="RESTRICT"),
        nullable=False,
        comment="主体主名称标签ID(level=2)",
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建人ID",
    )

    cover_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True, comment="首张提炼参考图封面"
    )
    cover_image: Mapped[Optional["Image"]] = relationship("Image", foreign_keys=[cover_image_id])

    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    category_tag: Mapped["Tag"] = relationship("Tag", foreign_keys=[category_tag_id])
    primary_tag: Mapped["Tag"] = relationship("Tag", foreign_keys=[primary_tag_id])
    samples: Mapped[list["SubjectSample"]] = relationship(
        "SubjectSample",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    image_subjects: Mapped[list["ImageSubject"]] = relationship(
        "ImageSubject",
        back_populates="subject",
        cascade="all, delete-orphan",
    )


class SubjectSample(Base):
    """主体样本向量。"""

    __tablename__ = "subject_samples"
    __table_args__ = (
        Index("ix_subject_samples_subject_id", "subject_id"),
        Index("ix_subject_samples_model", "embedding_model"),
        {"comment": "主体样本向量表"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        comment="主体ID",
    )
    image_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("images.id", ondelete="SET NULL"),
        nullable=True,
        comment="来源图片ID",
    )
    embedding_model: Mapped[str] = mapped_column(
        String(80),
        server_default="reference",
        nullable=False,
        comment="向量模型标识；V1 仅登记来源引用(reference)，真实向量由识别器接入后回填",
    )
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        # 维度不锁定：待真实识别器确定向量空间后再通过迁移固定维度并建索引
        Vector(None),
        nullable=True,
        comment="主体样本向量（V1 不写入）",
    )
    sample_meta: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="样本附加信息（如bbox）",
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建人ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
        comment="创建时间",
    )

    subject: Mapped["Subject"] = relationship("Subject", back_populates="samples")
    image: Mapped[Optional["Image"]] = relationship("Image")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])


class ImageSubject(Base, TimestampMixin):
    """图片主体判定结果。"""

    __tablename__ = "image_subjects"
    __table_args__ = (
        Index("ix_image_subjects_image_id", "image_id"),
        Index("ix_image_subjects_subject_id", "subject_id"),
        Index(
            "uq_image_subjects_primary",
            "image_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
        Index(
            "uq_image_subjects_image_subject",
            "image_id",
            "subject_id",
            unique=True,
        ),
        {"comment": "图片主体结果表"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")
    image_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        comment="图片ID",
    )
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        comment="主体ID",
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="置信度(0-1)",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        server_default="manual",
        nullable=False,
        comment="来源: manual/auto/approval/tag（人工标签确认）",
    )
    state: Mapped[str] = mapped_column(
        String(20),
        server_default="confirmed",
        nullable=False,
        comment="状态: 当前仅 confirmed（pending/rejected 预留给后续版本）",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
        comment="是否主主体",
    )
    is_current: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    synced_primary_tag_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        comment="由主体流程新增的主名称标签ID；仅该值对应的标签可在切换主体时移除",
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建人ID",
    )

    image: Mapped["Image"] = relationship("Image", back_populates="image_subjects")
    subject: Mapped["Subject"] = relationship("Subject", back_populates="image_subjects")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])


class SubjectPromptTemplate(Base, TimestampMixin):
    """提炼补充模板；任务保存文本快照，不依赖模板后续状态。"""

    __tablename__ = "subject_prompt_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)


class SubjectDefinitionVersion(Base):
    """主体描述被替换前的只读历史备份。"""

    __tablename__ = "subject_definition_versions"
    __table_args__ = (
        Index("ix_subject_versions_subject", "subject_id"),
        Index("uq_subject_published_revision", "subject_id", "published_revision", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="history")
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    recognition_notes: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    edit_revision: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    published_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
