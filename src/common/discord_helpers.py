import copy
import discord
from discord import Embed
from discord import Color
from datetime import timedelta
from PIL.Image import Resampling

from db.db_paradise import *
from api.game import *
from api.central import Player as CentralPlayer, Whitelist, WhitelistBan
from common.helpers import *

BYOND_ICON = "<:byond:1109845921904205874>"
SS14_ICON = "<:ss14:1109845956561735730>"
MISTAKE_ICON = "<:mistake:1283074454565556378>"
CHECKMARK_ICON = ":white_check_mark:"

DEPARTMENT_TRANSLATIONS = {
    "├Призраком": "Ghost",
    "└Живым": "Living",
    " ├Спец роли": "Special",
    " └Экипаж": "Crew",
    "ᅟ├Команд.": "Command",
    "ᅟ├Инженеры": "Engineering",
    "ᅟ├Медики": "Medical",
    "ᅟ├Учёные": "Science",
    "ᅟ├Снабжение": "Supply",
    "ᅟ├СБ": "Security",
    "ᅟ├Сервис": "Service",
    # "ᅟ├ВЛ": "Whitelist",
    "ᅟ└Синты": "Silicon",
}

SERVERS_NICE = {
    "136.243.82.223:4002": ["Main", "https://cdn.discordapp.com/emojis/1098305756836663379.webp?size=64"],
    "135.125.189.154:4002": ["Green", "https://cdn.discordapp.com/emojis/1098305756836663379.webp?size=64"],
    "141.95.72.94:4002": ["Green", "https://cdn.discordapp.com/emojis/1098305756836663379.webp?size=64"],
    "135.125.189.154:4001": ["Prime", "https://cdn.discordapp.com/emojis/1100109697744371852.webp?size=64"],
    "135.125.189.154:4000": ["Black", "https://cdn.discordapp.com/emojis/1098305756836663379.webp?size=64"]
}  # TODO: To config

MAX_FIELD_LENGTH = 1024

def embed_player_info(ingame_player_info: Paradise.Player | None, player_links: CentralPlayer | None, chars: Sequence[Paradise.Character]):
    if not player_links:
        return Embed(title="Дискорд игрока не привязан к игре.", color=Color.red())
    embed = Embed(
        title=f"Информация об игроке {player_links.id}",
        description=(
            f"**Дискорд:** <@{player_links.discord_id}>\n"
            f"**Сикей:** {player_links.ckey}\n"
        ),
        color=Color.blue()
    )
    if ingame_player_info:
        embed.description += (
            f"\n"
            f"**Ранг:** {ingame_player_info.last_admin_rank()}\n"
            f"**Стаж:** {ingame_player_info.lastseen - ingame_player_info.firstseen}\n"
            f"**Первое появление:** {ingame_player_info.firstseen}\n"
            f"**Последнее появление: **{ingame_player_info.lastseen}"
        )
        if ingame_player_info.exp:
            exp = parse_player_exp(ingame_player_info)
            embed.add_field(
                name=f"Время игры: {round((int(exp['Living']) + int(exp['Ghost'])) / 60, 2)} ч.",
                value=get_nice_exp(exp),
                inline=True)
    if len(chars):
        chars_info = get_nice_player_chars(chars)
        add_character_info(embed, chars_info)
    embed.set_footer(text="Тут был Фуриор")

    return embed


def get_nice_player_chars(chars: Sequence[Paradise.Character]):
    return '\n'.join(
        f"`{char.slot}:` **{char.real_name}**\n{gender_to_emoji(char.gender)} {char.species} {char.age} лет"
        for char in chars
    )

def add_character_info(embed: Embed, chars_info: str):
    if not len(chars_info):
        return
    base_field_name = "Персонажи"
    lines = chars_info.split("\n")
    # Один персонаж - две строки
    current_field_len = 0
    current_field_data = ""
    for i in range(0, len(lines), 2):
        potential_data = f"{lines[i]}\n{lines[i + 1]}\n"
        potential_data_len = len(potential_data)
        if current_field_len + potential_data_len > MAX_FIELD_LENGTH:
            embed.add_field(name=base_field_name, value=current_field_data, inline=True)
            base_field_name = ""
            current_field_data = ""
            current_field_len = 0

        current_field_len += potential_data_len
        current_field_data += potential_data
    if current_field_data:
        embed.add_field(name=base_field_name, value=current_field_data, inline=True)


def parse_player_exp(player: Paradise.Player):
    exp = player.exp
    departments = exp.split("&")
    result = {}
    for departments_exp_tuple in departments:
        dep, xp = departments_exp_tuple.split("=")
        result[dep] = xp
    return result


def get_nice_exp(exp: dict):
    return "".join(
        f"{departament}: {round(int(exp[DEPARTMENT_TRANSLATIONS[departament]]) / 60, 2)} ч.\n"
        for departament in DEPARTMENT_TRANSLATIONS
    )


def emojify_changelog(changelog: dict, emojified_tags: dict[str, str]):
    changelog_copy = copy.deepcopy(changelog)
    print(emojified_tags)
    for change in changelog_copy["changes"]:
        if change["tag"] in emojified_tags:
            change["tag"] = emojified_tags[change["tag"]]
        else:
            raise Exception(
                f"Invalid tag for emoji: {change}. Valid tags: {emojified_tags.keys()}")
    return changelog_copy


def gender_to_emoji(gender: str) -> str:
    match gender:
        case "male":
            return ":male_sign:"
        case "female":
            return ":female_sign:"
        case "plural":
            return ":regional_indicator_p:"
        case _:
            return ":helicopter:"


def get_nice_bans(bans: Sequence[Paradise.Ban]) -> list[Embed]:
    embeds = []
    if not bans:
        return []
    bans = convert_bans(bans)
    for ban in bans:
        match ban.bantype:
            case "PERMABAN":
                ban_color = Color.red()
                ban.bantype = "Пермабан"
            case "JOB_PERMABAN":
                ban_color = Color.purple()
                ban.bantype = "Пермаджоббан"
            case "TEMPBAN":
                ban_color = Color.orange()
                ban.bantype = "Темпбан"
            case "JOB_TEMPBAN":
                ban_color = Color.dark_blue()
                ban.bantype = "Джоббан"
            case "BAN":
                ban_color = Color.dark_red()
            case _:
                ban_color = Color.light_embed()
        if ban.unbanned or (ban.duration > 0 and ban.expiration_time < datetime.now()):
            ban_color = Color.green()
        embed = Embed(
            title=f"**{ban.bantype} {ban.id}**",
            description=f"**Игрок:** {ban.ckey}\n**Админ:** {ban.a_ckey}\n**Длительность:** {str(ban.duration // 60)} ч. до {str(ban.expiration_time) if ban.duration > 0 else 'Навсегда'}\n**Причина:** {ban.reason}\n{f'**Роль:** {ban.job}' if ban.job else ''}",
            color=ban_color,
        )
        embed.set_footer(
            text=f"{SERVERS_NICE[ban.serverip][0]} - {ban.expiration_time - timedelta(minutes=ban.duration)}",
            icon_url=SERVERS_NICE[ban.serverip][1]
        )
        embeds.append(embed)
    return embeds


def convert_bans(data: Sequence[Paradise.Ban]) -> Sequence[Paradise.Ban]:
    bans = list[Paradise.Ban]()
    for ban in data:
        sameban = False
        for nice_ban in bans:
            if (
                ban.reason == nice_ban.reason
                and ban.duration == nice_ban.duration
                and ban.bantype in ["JOB_TEMPBAN", "JOB_PERMABAN"]
            ):
                nice_ban.job = f"{nice_ban.job}, {ban.job}"
                nice_ban.id = ban.id
                sameban = True
        if not sameban:
            bans.append(ban)
    return bans


def embed_notes(notes: Sequence[Paradise.Note]):
    embeds = []
    for note in notes:
        embed = Embed(title="Нотес",
                      description=(
                          f"**Игрок:** {note.ckey}\n"
                          f"**Админ:** {note.adminckey}\n"
                          f"**Текст:** {note.notetext}"
                      ),
                      color=Color.light_embed())
        embed.set_footer(text=f"{note.server} - {note.timestamp}")
        embeds.append(embed)
    return embeds


def get_beautified_status(servers: list[Server]) -> str:
    res = ''
    for server in servers:
        server_info = server.get_server_status()
        res += (
            f"{BYOND_ICON if server.build == 'paradise' else SS14_ICON} "
            f"**{server.name}**: {server_info.players_num} [{server_info.round_duration}] {server_info.admins_num} A/M\n"
        )
    return res


def get_admins(servers: list[Server]) -> str:
    res = ''
    for server in servers:
        res += f"**{server.name}:**\n"
        admins = server.get_admin_who().admins
        if not admins:
            continue
        for admin in admins:
            if admin.get("stealth") != "STEALTH":
                res += f'  {admin["ckey"]} - {admin["rank"]}\n'
    return res


def get_players_online(server: Server) -> str:
    players_list = server.get_players_list()
    if not players_list.is_online:
        return f'**{server.name}:** OFFLINE'
    players_list = players_list.players
    return f"**{server.name}:** {', '.join(players_list)}"


def base64_to_discord_image(img_b64: str) -> discord.File:
    img_bytes = base64_to_image(img_b64)
    img = create_image_from_bytes(img_bytes)

    img = img.resize((img.size[0] * 4, img.size[1] * 4),
                     resample=Resampling.NEAREST)

    arr = BytesIO()
    img.save(arr, format='PNG')
    arr.seek(0)
    return discord.File(fp=arr, filename="article_photo.png")


def embed_player_whitelists(wls: list[Whitelist]) -> Embed:
    embed = Embed(
        title=f"Вайтлисты игрока {wls[0].player_id}" if wls else "У игроков нет вайтлистов",
        color=Color.green() if any(wl.valid and wl.expiration_time > datetime.now()
                                   for wl in wls) else Color.red()
    )

    if not wls:
        embed.description = "У игроков нет вайтлистов"
    else:
        format_wls_into_embed(wls, embed)
    return embed


def format_wls_into_embed(wls: list[Whitelist], embed: Embed):
    id_status = "\n".join(
        f"{'✅' if wl.valid and wl.expiration_time > datetime.now() else '⏳' if wl.expiration_time < datetime.now() else '❌'} "
        f"**#{wl.id:04}**"
        for wl in wls
    )

    servers = "\n".join(f"{wl.server_type}" for wl in wls)
    periods = "\n".join(
        f"{wl.issue_time.strftime('%d.%m.%Y')} - {wl.expiration_time.strftime('%d.%m.%Y')}" for wl in wls)

    embed.add_field(name="**ID и Статус**", value=id_status, inline=True)
    embed.add_field(name="**Сервер**", value=servers, inline=True)
    embed.add_field(name="**Срок**", value=periods, inline=True)


def embed_whitelist_bans(wl_bans: list[WhitelistBan]) -> list[Embed]:
    embeds = []
    embeds.extend(
        Embed(
            title=f"Выписка #{ban.id:04} {'<:Deadge:1173397059857035364>' if not ban.valid else '<:sus:1291534540073861152>' if ban.expiration_time < datetime.now() else '<:gonnacryhampter:1213341826958762044>'}",
            description=(
                f"**Игрок:** {ban.player_id}\n"
                f"**Номер выписки:** #{ban.id:04}\n"
                f"**Сервер:** {ban.server_type}\n"
                f"**Дата выписки:** {ban.issue_time}\n"
                f"**Дата истечения:** {ban.expiration_time}\n"
                f"**Админ:** {ban.admin_id}\n"
                f"**Причина:** {ban.reason}"
            ),
            color=(
                Color.red()
                if ban.valid and ban.expiration_time > datetime.now()
                else Color.green()
            ),
        )
        for ban in wl_bans
    )
    return embeds
