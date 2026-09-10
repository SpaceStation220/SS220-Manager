from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

    from api.central import BenefitGrant, Central


async def snapshot_tiers(
    *,
    central: Central,
    discord_id: int,
    scopes: Iterable[str],
) -> dict[str, int]:
    benefits = await central.get_player_active_benefits(discord_id=discord_id)
    return {
        scope: effective_benefit_tier(grants=benefits, scope=scope)
        for scope in scopes
    }


def effective_benefit_tier(
    *,
    grants: Iterable[BenefitGrant],
    scope: str | None = None,
) -> int:
    return max(
        (grant.tier for grant in grants if scope is None or grant.scope == scope),
        default=0,
    )


def causes_for_roles(
    *,
    role_ids: set[int],
    role_to_causes: Mapping[int, set[str]],
) -> set[str]:
    return {
        cause
        for role_id in role_ids
        for cause in role_to_causes.get(role_id, ())
    }


async def sync_whitelists(
    *,
    central: Central,
    discord_id: int,
    server_types: set[str],
    admin_discord_id: int,
    revoke: bool,
) -> None:
    for server_type in server_types:
        if revoke:
            await central.remove_whitelist_discord(
                player_discord_id=discord_id,
                admin_discord_id=admin_discord_id,
                server_type=server_type,
            )
        else:
            await central.give_whitelist_discord(
                player_discord_id=discord_id,
                admin_discord_id=admin_discord_id,
                server_type=server_type,
                duration_days=7777,
            )


async def sync_member_update(
    *,
    before: discord.Member,
    after: discord.Member,
    central: Central,
    role_to_causes: Mapping[int, set[str]],
    whitelist_server_types: Mapping[str, str],
    threshold: int,
    admin_discord_id: int,
) -> None:
    if before.roles == after.roles:
        return

    async def sync_causes(
        *,
        causes: set[str],
        action: Callable[[str], Awaitable[object]],
        should_sync: Callable[[int, int], bool],
        revoke: bool,
    ) -> None:
        if not causes:
            return

        tiers_before = await snapshot_tiers(
            central=central,
            discord_id=after.id,
            scopes=whitelist_server_types,
        )
        for cause in causes:
            await action(cause)
        tiers_after = await snapshot_tiers(
            central=central,
            discord_id=after.id,
            scopes=whitelist_server_types,
        )
        logging.debug(
            "User %s benefit tiers changed from %s to %s",
            after.id, tiers_before, tiers_after
        )
        server_types = {
            server_type
            for scope, server_type in whitelist_server_types.items()
            if should_sync(tiers_before[scope], tiers_after[scope])
        }
        await sync_whitelists(
            central=central,
            discord_id=after.id,
            server_types=server_types,
            admin_discord_id=admin_discord_id,
            revoke=revoke,
        )

    removed_role_ids = {role.id for role in before.roles} - {
        role.id for role in after.roles
    }
    await sync_causes(
        causes=causes_for_roles(
            role_ids=removed_role_ids,
            role_to_causes=role_to_causes,
        ),
        action=lambda cause: central.revoke_benefits(
            discord_id=after.id, cause=cause
        ),
        should_sync=lambda before_tier, after_tier: (
            before_tier >= threshold > after_tier
        ),
        revoke=True,
    )

    added_role_ids = {role.id for role in after.roles} - {
        role.id for role in before.roles
    }
    await sync_causes(
        causes=causes_for_roles(
            role_ids=added_role_ids,
            role_to_causes=role_to_causes,
        ),
        action=lambda cause: central.grant_benefit(
            discord_id=after.id,
            cause=cause,
            scope="*",
            duration_days=7777,
        ),
        should_sync=lambda before_tier, after_tier: (
            before_tier < threshold <= after_tier
        ),
        revoke=False,
    )
