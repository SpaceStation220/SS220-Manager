import types
import re
import base64
from PIL import Image, ImageFile
from io import BytesIO

CL_BODY = re.compile(
    r"(:cl:|🆑)[ \t]*(?P<author>.+?)?\s*\n(?P<content>(.|\n)*?)\n/(:cl:|🆑)", re.MULTILINE)
CL_SPLIT = re.compile(r"\s*(?:(?P<tag>\w+)\s*:)?\s*(?P<message>.*)")


def build_changelog(pr: dict, valid_tags: dict[str, str]) -> dict[str, str]:
    changelog = parse_changelog(pr["body"], valid_tags)
    changelog["author"] = changelog["author"] or pr["user"]["login"]
    changelog["labels"] = [label["name"] for label in pr["labels"]]
    return changelog


def parse_changelog(pr_body: str, valid_tags: dict[str, str]) -> dict:
    clean_pr_body = re.sub(r"<!--.*?-->", "", pr_body, flags=re.DOTALL)
    cl_parse_result = CL_BODY.search(clean_pr_body)
    if cl_parse_result is None:
        raise Exception(
            "Failed to parse the changelog. Check changelog format.")
    cl_changes = []
    for cl_line in cl_parse_result.group("content").splitlines():
        if not cl_line:
            continue
        change_parse_result = CL_SPLIT.search(cl_line)
        if not change_parse_result:
            raise Exception(f"Invalid change: '{cl_line}'")
        tag = change_parse_result.group("tag")
        message = change_parse_result.group("message")

        if not tag and not message:
            continue
        if not message:
            raise Exception(f"No message for change: '{cl_line}'")

        message = message.strip()

        if tag:
            if tag in valid_tags:
                cl_changes.append({
                    "tag": valid_tags[tag],
                    "message": message
                })
            else:
                raise Exception(f"Invalid tag: '{cl_line}'")
        # Append line without tag to the previous change
        else:
            if len(cl_changes):
                prev_change = cl_changes[-1]
                prev_change["message"] += f" {message}"
            else:
                raise Exception(f"Change with no tag: {cl_line}")

    if len(cl_changes) == 0:
        raise Exception(
            "No changes found in the changelog. Use special label if changelog is not expected.")
    return {
        # I want this to be None, not empty
        "author": str.strip(cl_parse_result.group("author") or "") or None,
        "changes": cl_changes
    }


def sanitize_ckey(ckey: str) -> str:
    return ''.join(char for char in ckey if char.isalnum()).lower() if ckey else ""


ERRORS = types.SimpleNamespace()
ERRORS.ERR_BOUND = "err_bound"
ERRORS.ERR_404 = "err_404"


def base64_to_image(base64_string: str) -> bytes:
    if "data:image" in base64_string:
        base64_string = base64_string.split(",")[1]

    image_bytes = base64.b64decode(base64_string)
    return image_bytes


def create_image_from_bytes(image_bytes: bytes) -> ImageFile.ImageFile:
    image_stream = BytesIO(image_bytes)
    image = Image.open(image_stream)
    return image
