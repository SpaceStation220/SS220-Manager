import logging
from collections.abc import Mapping


def effective_benefit_tier(grants, scope: str | None = None) -> int:
    return max(
        (grant.tier for grant in grants if scope is None or grant.scope == scope),
        default=0,
    )


def causes_for_roles(
    role_ids: set[int], role_to_causes: Mapping[int, set[str]]
) -> set[str]:
    return {
        cause
        for role_id in role_ids
        for cause in role_to_causes.get(role_id, ())
    }


async def snapshot_tiers(central, discord_id: int, scopes) -> dict[str, int]:
    benefits = await central.get_player_active_benefits(discord_id)
    return {scope: effective_benefit_tier(benefits, scope) for scope in scopes}


async def sync_member_update(
    before,
    after,
    central,
    role_to_causes: Mapping[int, set[str]],
    whitelist_server_types: Mapping[str, str],
    threshold: int,
    admin_discord_id: int,
) -> None:
    if before.roles == after.roles:
        return

    async def sync_whitelists(causes, per_cause_action, should_sync, on_result):
        if not causes:
            return
        tiers_before = await snapshot_tiers(
            central, after.id, whitelist_server_types
        )
        for cause in causes:
            await per_cause_action(cause)
        tiers_after = await snapshot_tiers(
            central, after.id, whitelist_server_types
        )
        logging.debug(
            "User %s benefit tiers changed from %s to %s",
            after.id, tiers_before, tiers_after
        )
        server_types = {
            server_type
            for scope, server_type in whitelist_server_types.items()
            if should_sync(tiers_after[scope])
        }
        for server_type in server_types:
            await on_result(server_type)

    removed_causes = causes_for_roles(
        {role.id for role in before.roles} - {role.id for role in after.roles},
        role_to_causes,
    )
    await sync_whitelists(
        removed_causes,
        lambda cause: central.revoke_benefits(after.id, cause),
        lambda tier: tier < threshold,
        lambda server_type: central.remove_whitelist_discord(
            after.id, admin_discord_id, server_type
        ),
    )

    added_causes = causes_for_roles(
        {role.id for role in after.roles} - {role.id for role in before.roles},
        role_to_causes,
    )
    await sync_whitelists(
        added_causes,
        lambda cause: central.grant_benefit(after.id, cause, "*", 7777),
        lambda tier: tier >= threshold,
        lambda server_type: central.give_whitelist_discord(
            after.id, admin_discord_id, server_type, 7777
        ),
    )
