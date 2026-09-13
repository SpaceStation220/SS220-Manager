import unittest
from dataclasses import dataclass, field, replace
from unittest.mock import AsyncMock, Mock

from common.benefit_sync import BenefitSyncConfig, sync_member_update


PLAYER_ID = 42
BOT_ID = 99
DEVELOPER_ROLE_ID = 1
MENTOR_ROLE_ID = 2
UNRELATED_ROLE_ID = 999
DEVELOPER_CAUSE = "developer@discord"
MENTOR_CAUSE = "mentor@bandastation"
PRIME_SERVER = "prime"
FOREVER_DAYS = 7777
QUALIFYING_TIER = 2
HIGHER_TIER = 3
CREATED_STATUS = 201
WHITELIST_ID = 10

SYNC_CONFIG = BenefitSyncConfig(
    role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}, MENTOR_ROLE_ID: {MENTOR_CAUSE}},
    whitelisted_benefit_causes={DEVELOPER_CAUSE: [PRIME_SERVER], MENTOR_CAUSE: [PRIME_SERVER]},
    admin_discord_id=BOT_ID,
)
ROLE_SYNC_CONFIG = replace(SYNC_CONFIG, server_type_roles={PRIME_SERVER: 100})


@dataclass(frozen=True)
class Role:
    id: int


@dataclass(frozen=True)
class Guild:
    roles: list[Role]


@dataclass(frozen=True)
class Member:
    id: int
    roles: list[Role]
    guild: Guild | None = None
    added_roles: list[Role] = field(default_factory=list)
    removed_roles: list[Role] = field(default_factory=list)

    async def add_roles(self, role: Role):
        self.added_roles.append(role)

    async def remove_roles(self, role: Role):
        self.removed_roles.append(role)


@dataclass(frozen=True)
class Grant:
    tier: int
    cause: str


def central_with_benefit_snapshots(*snapshots):
    central = Mock()
    central.get_player_active_benefits = AsyncMock(side_effect=snapshots)
    central.grant_benefit = AsyncMock(return_value=[])
    central.revoke_benefits = AsyncMock()
    central.give_whitelist_discord = AsyncMock(
        return_value=(CREATED_STATUS, Mock(id=WHITELIST_ID))
    )
    central.remove_whitelist_discord = AsyncMock()
    return central


class TestBenefitSync(unittest.IsolatedAsyncioTestCase):
    async def test_add_grants_benefit_and_whitelist(self):
        central = central_with_benefit_snapshots(
            [], [Grant(tier=QUALIFYING_TIER, cause=DEVELOPER_CAUSE)]
        )

        after = Member(
            PLAYER_ID,
            [Role(DEVELOPER_ROLE_ID)],
            guild=Guild([Role(100)]),
        )
        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=after,
            central=central,
            config=ROLE_SYNC_CONFIG,
        )

        central.grant_benefit.assert_awaited_once_with(
            discord_id=PLAYER_ID,
            cause=DEVELOPER_CAUSE,
            scopes=["*"],
            duration_days=FOREVER_DAYS,
        )
        central.give_whitelist_discord.assert_awaited_once_with(
            player_discord_id=PLAYER_ID,
            admin_discord_id=BOT_ID,
            server_type=PRIME_SERVER,
            duration_days=FOREVER_DAYS,
        )
        self.assertEqual([100], [role.id for role in after.added_roles])

    async def test_adding_role_for_qualified_user_keeps_whitelist_unique(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=HIGHER_TIER, cause=DEVELOPER_CAUSE)],
            [Grant(tier=HIGHER_TIER, cause=DEVELOPER_CAUSE)],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            central=central,
            config=SYNC_CONFIG,
        )

        central.grant_benefit.assert_awaited_once()
        central.give_whitelist_discord.assert_not_awaited()

    async def test_remove_last_qualifying_grant_removes_whitelist(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=QUALIFYING_TIER, cause=DEVELOPER_CAUSE)], []
        )

        after = Member(PLAYER_ID, [], guild=Guild([Role(100)]))
        await sync_member_update(
            before=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            after=after,
            central=central,
            config=ROLE_SYNC_CONFIG,
        )

        central.revoke_benefits.assert_awaited_once_with(
            discord_id=PLAYER_ID,
            cause=DEVELOPER_CAUSE,
        )
        central.remove_whitelist_discord.assert_awaited_once_with(
            player_discord_id=PLAYER_ID,
            admin_discord_id=BOT_ID,
            server_type=PRIME_SERVER,
        )
        self.assertEqual([100], [role.id for role in after.removed_roles])

    async def test_removing_lower_grant_keeps_whitelist(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=HIGHER_TIER, cause=DEVELOPER_CAUSE)],
            [Grant(tier=HIGHER_TIER, cause=DEVELOPER_CAUSE)],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            after=Member(PLAYER_ID, []),
            central=central,
            config=SYNC_CONFIG,
        )

        central.revoke_benefits.assert_awaited_once()
        central.remove_whitelist_discord.assert_not_awaited()

    async def test_multiple_causes_mapping_to_one_server_are_deduplicated(self):
        central = central_with_benefit_snapshots(
            [],
            [
                Grant(tier=QUALIFYING_TIER, cause=DEVELOPER_CAUSE),
                Grant(tier=QUALIFYING_TIER, cause=MENTOR_CAUSE),
            ],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID), Role(MENTOR_ROLE_ID)]),
            central=central,
            config=SYNC_CONFIG,
        )

        self.assertEqual(2, central.grant_benefit.await_count)
        central.give_whitelist_discord.assert_awaited_once_with(
            player_discord_id=PLAYER_ID,
            admin_discord_id=BOT_ID,
            server_type=PRIME_SERVER,
            duration_days=FOREVER_DAYS,
        )

    async def test_unrelated_role_change_does_not_call_central(self):
        central = central_with_benefit_snapshots()

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(UNRELATED_ROLE_ID)]),
            central=central,
            config=SYNC_CONFIG,
        )

        central.get_player_active_benefits.assert_not_awaited()
        central.grant_benefit.assert_not_awaited()
        central.revoke_benefits.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
