from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

    from api.central import Central
    from api.central import BenefitGrant


@dataclass
class BenefitSyncConfig:
    role_to_causes: Mapping[int, set[str]]
    whitelist_server_types: Mapping[str, str]
    threshold: int
    admin_discord_id: int
    server_type_roles: Mapping[str, int] | None = None


async def snapshot_tiers(
    central: Central,
    discord_id: int,
    scopes: Iterable[str],
) -> dict[str, int]:
    benefits = await central.get_player_active_benefits(discord_id=discord_id)
    return {
        scope: effective_benefit_tier(benefits, scope)
        for scope in scopes
    }


def effective_benefit_tier(
    grants: Iterable[BenefitGrant],
    scope: str | None = None,
) -> int:
    return max(
        (grant.tier for grant in grants if scope is None or grant.scope == scope),
        default=0,
    )


def causes_for_roles(
    role_ids: set[int],
    role_to_causes: Mapping[int, set[str]],
) -> set[str]:
    return {
        cause
        for role_id in role_ids
        for cause in role_to_causes.get(role_id, ())
    }


class BenefitSynchronizer:
    def __init__(self, central: Central, member: discord.Member, config: BenefitSyncConfig):
        self.central = central
        self.member = member
        self.config = config

    async def run(self, before: discord.Member) -> None:
        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in self.member.roles}

        await self._sync_causes(
            causes_for_roles(
                before_roles - after_roles,
                self.config.role_to_causes,
            ),
            revoke=True,
        )
        await self._sync_causes(
            causes_for_roles(
                after_roles - before_roles,
                self.config.role_to_causes,
            ),
            revoke=False,
        )

    async def _sync_causes(self, causes: set[str], revoke: bool) -> None:
        if not causes:
            return

        scopes = self.config.whitelist_server_types
        tiers_before = await snapshot_tiers(self.central, self.member.id, scopes)
        for cause in causes:
            if revoke:
                await self.central.revoke_benefits(
                    discord_id=self.member.id,
                    cause=cause,
                )
            else:
                await self.central.grant_benefit(
                    discord_id=self.member.id,
                    cause=cause,
                    scopes=["*"],  # resolved to all active scopes by SSC
                    duration_days=7777,
                )
        tiers_after = await snapshot_tiers(self.central, self.member.id, scopes)
        logging.debug(
            "User %s benefit tiers changed from %s to %s",
            self.member.id,
            tiers_before,
            tiers_after,
        )

        server_types = {
            server_type
            for scope, server_type in scopes.items()
            if self._should_sync(tiers_before[scope], tiers_after[scope], revoke)
        }
        for server_type in server_types:
            await self._sync_whitelist(server_type, revoke)

    def _should_sync(self, before: int, after: int, revoke: bool) -> bool:
        if revoke:
            return before >= self.config.threshold > after
        return before < self.config.threshold <= after

    async def _sync_whitelist(self, server_type: str, revoke: bool) -> None:
        role = self._find_server_role(server_type)
        if revoke:
            await self.central.remove_whitelist_discord(
                player_discord_id=self.member.id,
                admin_discord_id=self.config.admin_discord_id,
                server_type=server_type,
            )
            if role:
                await self.member.remove_roles(role)
                logging.info("Removed role for %s from %s", server_type, self.member.id)
            return

        status, _ = await self.central.give_whitelist_discord(
            player_discord_id=self.member.id,
            admin_discord_id=self.config.admin_discord_id,
            server_type=server_type,
            duration_days=7777,
        )
        if status == 201 and role:
            await self.member.add_roles(role)
            logging.info("Added role for %s to %s", server_type, self.member.id)

    def _find_server_role(self, server_type: str):
        if self.config.server_type_roles is None:
            return None
        role_id = self.config.server_type_roles.get(server_type)
        role = next(
            (role for role in self.member.guild.roles if role.id == role_id),
            None,
        ) if role_id is not None else None
        if role is None:
            logging.error("Role for %s not found", server_type)
        return role


async def sync_member_update(
    before: discord.Member,
    after: discord.Member,
    central: Central,
    config: BenefitSyncConfig,
) -> None:
    if before.roles == after.roles:
        return
    await BenefitSynchronizer(central, after, config).run(before)
