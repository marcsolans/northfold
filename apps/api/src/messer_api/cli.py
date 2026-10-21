"""Operational commands: ``python -m messer_api.cli bootstrap|seed|create-superadmin``."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid

from sqlalchemy import select

from messer_common.db import dispose_engines, system_session
from messer_common.db.models import AuthCredential, Membership, Org, User
from messer_common.logging import configure_logging, get_logger
from messer_common.security import hash_password
from messer_common.settings import get_settings

from .services.orgs import create_org
from .services.seed import seed_reference_data

log = get_logger("messer.cli")


async def create_superadmin(email: str, password: str | None) -> tuple[User, str | None]:
    generated: str | None = None
    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if user is None:
            user = User(id=uuid.uuid4(), email=email.lower(), name="Messer Admin", is_superadmin=True)
            s.add(user)
            await s.flush()
            if not password:
                generated = secrets.token_urlsafe(14)
            s.add(AuthCredential(user_id=user.id, password_hash=hash_password(password or generated or "")))
        else:
            user.is_superadmin = True
            if password:
                cred = await s.get(AuthCredential, user.id)
                if cred is None:
                    s.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
                else:
                    cred.password_hash = hash_password(password)
    return user, generated


async def bootstrap() -> None:
    settings = get_settings()
    async with system_session() as s:
        await seed_reference_data(s)
    user, generated = await create_superadmin(
        settings.messer_superadmin_email, settings.messer_superadmin_password or None
    )
    async with system_session() as s:
        has_org = (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).first()
        if has_org is None:
            owner = await s.get(User, user.id)
            assert owner is not None
            org = await create_org(s, owner=owner, name="Messer", slug="messer")
            log.info("bootstrap.org_created", org_id=str(org.id))
        else:
            org = await s.get(Org, has_org[0])
    sys.stdout.write(f"Superadmin: {user.email}\n")
    if generated:
        sys.stdout.write(f"Generated password (store it now, it is not shown again): {generated}\n")
    sys.stdout.write("Plans, model prices, feature flags, connectors and templates are seeded.\n")


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "bootstrap":
            await bootstrap()
        elif args.command == "seed":
            async with system_session() as s:
                await seed_reference_data(s)
        elif args.command == "create-superadmin":
            user, generated = await create_superadmin(args.email, args.password)
            sys.stdout.write(f"Superadmin: {user.email}\n")
            if generated:
                sys.stdout.write(f"Generated password: {generated}\n")
    finally:
        await dispose_engines()


def main() -> None:
    configure_logging("cli")
    parser = argparse.ArgumentParser(prog="messer-api")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Seed reference data, create the superadmin and the first organization")
    sub.add_parser("seed", help="Seed plans, model prices, flags, connectors and templates (idempotent)")
    sa = sub.add_parser("create-superadmin")
    sa.add_argument("email")
    sa.add_argument("--password", default=None)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
