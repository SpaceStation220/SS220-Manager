import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

from common.benefit_sync import sync_member_update


PLAYER_ID = 42
BOT_ID = 99
DEVELOPER_ROLE_ID = 1
MENTOR_ROLE_ID = 2
UNRELATED_ROLE_ID = 999
DEVELOPER_CAUSE = "developer@discord"
MENTOR_CAUSE = "mentor@bandastation"
BANDASTATION_SCOPE = "bandastation"
LEGACY_SCOPE = "legacy"
PRIME_SERVER = "prime"
WHITELIST_THRESHOLD = 2
FOREVER_DAYS = 7777
QUALIFYING_TIER = 2
HIGHER_TIER = 3
CREATED_STATUS = 201
WHITELIST_ID = 10


@dataclass(frozen=True)
class Role:
    id: int


@dataclass(frozen=True)
class Member:
    id: int
    roles: list[Role]


@dataclass(frozen=True)
class Grant:
    tier: int
    scope: str


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
            [], [Grant(tier=QUALIFYING_TIER, scope=BANDASTATION_SCOPE)]
        )

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            central=central,
            role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}},
            whitelist_server_types={BANDASTATION_SCOPE: PRIME_SERVER},
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
        )

        central.grant_benefit.assert_awaited_once_with(
            discord_id=PLAYER_ID,
            cause=DEVELOPER_CAUSE,
            scope="*",
            duration_days=FOREVER_DAYS,
        )
        central.give_whitelist_discord.assert_awaited_once_with(
            player_discord_id=PLAYER_ID,
            admin_discord_id=BOT_ID,
            server_type=PRIME_SERVER,
            duration_days=FOREVER_DAYS,
        )

    async def test_adding_role_for_qualified_user_keeps_whitelist_unique(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=HIGHER_TIER, scope=BANDASTATION_SCOPE)],
            [Grant(tier=HIGHER_TIER, scope=BANDASTATION_SCOPE)],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            central=central,
            role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}},
            whitelist_server_types={BANDASTATION_SCOPE: PRIME_SERVER},
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
        )

        central.grant_benefit.assert_awaited_once()
        central.give_whitelist_discord.assert_not_awaited()

    async def test_remove_last_qualifying_grant_removes_whitelist(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=QUALIFYING_TIER, scope=BANDASTATION_SCOPE)], []
        )

        await sync_member_update(
            before=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            after=Member(PLAYER_ID, []),
            central=central,
            role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}},
            whitelist_server_types={BANDASTATION_SCOPE: PRIME_SERVER},
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
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

    async def test_removing_lower_grant_keeps_whitelist(self):
        central = central_with_benefit_snapshots(
            [Grant(tier=HIGHER_TIER, scope=BANDASTATION_SCOPE)],
            [Grant(tier=HIGHER_TIER, scope=BANDASTATION_SCOPE)],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID)]),
            after=Member(PLAYER_ID, []),
            central=central,
            role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}},
            whitelist_server_types={BANDASTATION_SCOPE: PRIME_SERVER},
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
        )

        central.revoke_benefits.assert_awaited_once()
        central.remove_whitelist_discord.assert_not_awaited()

    async def test_multiple_scopes_mapping_to_one_server_are_deduplicated(self):
        central = central_with_benefit_snapshots(
            [],
            [
                Grant(tier=QUALIFYING_TIER, scope=BANDASTATION_SCOPE),
                Grant(tier=QUALIFYING_TIER, scope=LEGACY_SCOPE),
            ],
        )

        await sync_member_update(
            before=Member(PLAYER_ID, []),
            after=Member(PLAYER_ID, [Role(DEVELOPER_ROLE_ID), Role(MENTOR_ROLE_ID)]),
            central=central,
            role_to_causes={
                DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE},
                MENTOR_ROLE_ID: {MENTOR_CAUSE},
            },
            whitelist_server_types={
                BANDASTATION_SCOPE: PRIME_SERVER,
                LEGACY_SCOPE: PRIME_SERVER,
            },
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
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
            role_to_causes={DEVELOPER_ROLE_ID: {DEVELOPER_CAUSE}},
            whitelist_server_types={BANDASTATION_SCOPE: PRIME_SERVER},
            threshold=WHITELIST_THRESHOLD,
            admin_discord_id=BOT_ID,
        )

        central.get_player_active_benefits.assert_not_awaited()
        central.grant_benefit.assert_not_awaited()
        central.revoke_benefits.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
