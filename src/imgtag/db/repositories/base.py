"""Base repository with common CRUD operations.

Provides a generic base class for all repository implementations.
"""

from typing import Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.models.base import Base

# Generic type for model classes
ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic base repository with common database operations.

    Subclasses should specify the model class and can add specialized methods.

    Example:
        class UserRepository(BaseRepository[User]):
            model = User

            async def get_by_username(self, session: AsyncSession, username: str):
                return await self.get_by_field(session, "username", username)
    """

    model: Type[ModelT]

    async def get_by_id(
        self,
        session: AsyncSession,
        id_value: int | str,
    ) -> Optional[ModelT]:
        """Get a single record by primary key.

        Args:
            session: Database session.
            id_value: Primary key value.

        Returns:
            Model instance or None if not found.
        """
        return await session.get(self.model, id_value)

    async def get_by_field(
        self,
        session: AsyncSession,
        field_name: str,
        value: any,
    ) -> Optional[ModelT]:
        """Get a single record by field value.

        Args:
            session: Database session.
            field_name: Name of the field to filter by.
            value: Value to match.

        Returns:
            First matching model instance or None.
        """
        stmt = select(self.model).where(
            getattr(self.model, field_name) == value
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        """Get all records with pagination.

        Args:
            session: Database session.
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            List of model instances.
        """
        stmt = select(self.model).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        session: AsyncSession,
        **kwargs,
    ) -> ModelT:
        """Create a new record.

        Args:
            session: Database session.
            **kwargs: Field values for the new record.

        Returns:
            Created model instance.
        """
        instance = self.model(**kwargs)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance

    async def update(
        self,
        session: AsyncSession,
        instance: ModelT,
        **kwargs,
    ) -> ModelT:
        """Update an existing record.

        Args:
            session: Database session.
            instance: Model instance to update.
            **kwargs: Field values to update.

        Returns:
            Updated model instance.
        """
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await session.flush()
        await session.refresh(instance)
        return instance

    async def delete(
        self,
        session: AsyncSession,
        instance: ModelT,
    ) -> None:
        """Delete a record.

        Args:
            session: Database session.
            instance: Model instance to delete.
        """
        await session.delete(instance)
        await session.flush()

    async def count(self, session: AsyncSession) -> int:
        """Count total records.

        Args:
            session: Database session.

        Returns:
            Total count of records.
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model)
        result = await session.execute(stmt)
        return result.scalar() or 0
