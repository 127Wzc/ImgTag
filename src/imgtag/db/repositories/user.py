"""User repository for user-related database operations.

Provides user authentication, management, and API key operations.
"""

import secrets
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.user import User


class UserRepository(BaseRepository[User]):
    """Repository for User model with authentication operations.

    Includes methods for:
    - User authentication (by username, email, API key)
    - Password management
    - API key generation
    - Admin operations
    """

    model = User

    async def get_by_username(
        self,
        session: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """Find user by username.

        Args:
            session: Database session.
            username: Username to search for.

        Returns:
            User instance or None if not found.
        """
        return await self.get_by_field(session, "username", username)

    async def get_by_email(
        self,
        session: AsyncSession,
        email: str,
    ) -> Optional[User]:
        """Find user by email.

        Args:
            session: Database session.
            email: Email to search for.

        Returns:
            User instance or None if not found.
        """
        if not email:
            return None
        return await self.get_by_field(session, "email", email)

    async def get_by_api_key(
        self,
        session: AsyncSession,
        api_key: str,
    ) -> Optional[User]:
        """Find user by API key.

        Args:
            session: Database session.
            api_key: API key to search for.

        Returns:
            User instance or None if not found.
        """
        if not api_key:
            return None
        stmt = select(User).where(
            User.api_key == api_key,
            User.is_active == True,  # noqa: E712
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        session: AsyncSession,
        username: str,
        password_hash: str,
        *,
        email: Optional[str] = None,
        role: str = "user",
    ) -> User:
        """Create a new user.

        Args:
            session: Database session.
            username: Unique username.
            password_hash: Hashed password (salt$hash format).
            email: Optional email address.
            role: User role (user/admin).

        Returns:
            Created User instance.

        Raises:
            IntegrityError: If username or email already exists.
        """
        return await self.create(
            session,
            username=username,
            password_hash=password_hash,
            email=email,
            role=role,
            is_active=True,
        )

    async def update_password(
        self,
        session: AsyncSession,
        user: User,
        new_password_hash: str,
    ) -> User:
        """Update user password.

        Args:
            session: Database session.
            user: User instance to update.
            new_password_hash: New hashed password.

        Returns:
            Updated User instance.
        """
        return await self.update(session, user, password_hash=new_password_hash)

    async def update_last_login(
        self,
        session: AsyncSession,
        user: User,
    ) -> User:
        """Update user's last login timestamp.

        Args:
            session: Database session.
            user: User instance to update.

        Returns:
            Updated User instance.
        """
        from datetime import datetime, timezone

        return await self.update(
            session, user, last_login_at=datetime.now(timezone.utc)
        )

    async def set_active(
        self,
        session: AsyncSession,
        user: User,
        is_active: bool,
    ) -> User:
        """Set user active status.

        Args:
            session: Database session.
            user: User instance to update.
            is_active: Active status.

        Returns:
            Updated User instance.
        """
        return await self.update(session, user, is_active=is_active)

    async def set_role(
        self,
        session: AsyncSession,
        user: User,
        role: str,
    ) -> User:
        """Set user role.

        Args:
            session: Database session.
            user: User instance to update.
            role: New role (user/admin).

        Returns:
            Updated User instance.
        """
        return await self.update(session, user, role=role)

    async def generate_api_key(
        self,
        session: AsyncSession,
        user: User,
    ) -> str:
        """Generate and save a new API key for user.

        Args:
            session: Database session.
            user: User instance.

        Returns:
            Generated API key string.
        """
        api_key = secrets.token_hex(32)  # 64 characters
        await self.update(session, user, api_key=api_key)
        return api_key

    async def delete_api_key(
        self,
        session: AsyncSession,
        user: User,
    ) -> User:
        """Delete user's API key.

        Args:
            session: Database session.
            user: User instance.

        Returns:
            Updated User instance.
        """
        return await self.update(session, user, api_key=None)

    async def get_all_users(
        self,
        session: AsyncSession,
        *,
        include_inactive: bool = True,
    ) -> Sequence[User]:
        """Get all users.

        Args:
            session: Database session.
            include_inactive: Include inactive users.

        Returns:
            List of User instances.
        """
        stmt = select(User).order_by(User.id.asc())
        if not include_inactive:
            stmt = stmt.where(User.is_active == True)  # noqa: E712
        result = await session.execute(stmt)
        return result.scalars().all()

    async def username_exists(
        self,
        session: AsyncSession,
        username: str,
    ) -> bool:
        """Check if username exists.

        Args:
            session: Database session.
            username: Username to check.

        Returns:
            True if username exists, False otherwise.
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(User).where(User.username == username)
        result = await session.execute(stmt)
        return (result.scalar() or 0) > 0


# Singleton instance
user_repository = UserRepository()
