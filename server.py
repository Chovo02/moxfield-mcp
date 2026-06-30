#!/usr/bin/env python3
"""
MCP Server for Moxfield (Magic: The Gathering deckbuilding platform).

Moxfield has no official public API. This server calls the same JSON
endpoints (api2.moxfield.com) that moxfield.com's own frontend uses.
These endpoints are undocumented and unofficial — they may change or
break without notice. Moxfield enforces Cloudflare bot protection, so
all requests include browser-like headers.

Tools:
    - moxfield_search_decks: search public decklists on Moxfield
    - moxfield_get_deck: fetch a specific deck's full card list and stats
    - moxfield_search_cards: search Moxfield's card database with prices and legalities
"""

import json
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

mcp = FastMCP(
    "moxfield_mcp",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    stateless_http=True,
    json_response=True,
)

API_BASE_URL = "https://api2.moxfield.com"
REQUEST_TIMEOUT = 30.0
MOXFIELD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.moxfield.com",
    "Referer": "https://www.moxfield.com/",
}


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _extract_public_id(deck_url_or_id: str) -> str:
    """Extract the Moxfield publicId from a full URL or return the raw ID.

    Accepts strings like:
    - "https://moxfield.com/decks/F62pAiveVUGu9D3pIwFsnA"
    - "F62pAiveVUGu9D3pIwFsnA"
    """
    match = re.search(r"moxfield\.com/decks/([A-Za-z0-9_-]+)", deck_url_or_id)
    return match.group(1) if match else deck_url_or_id.strip()


async def _get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/{endpoint}",
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers=MOXFIELD_HEADERS,
        )
        if response.status_code == 404:
            raise LookupError(f"Not found: {endpoint}")
        response.raise_for_status()
        return response.json()


def _handle_api_error(e: Exception, context: str = "") -> str:
    prefix = f"Error{f' ({context})' if context else ''}: "
    if isinstance(e, LookupError):
        return f"{prefix}{e}"
    if isinstance(e, httpx.HTTPStatusError):
        return f"{prefix}Request failed with status {e.response.status_code}."
    if isinstance(e, httpx.TimeoutException):
        return f"{prefix}Request to Moxfield timed out. Please try again."
    return f"{prefix}Unexpected error: {type(e).__name__}: {e}"


def _format_usd(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"${float(val):.2f}"
    except (TypeError, ValueError):
        return str(val)


def _card_line_md(name: str, quantity: int, entry: Dict[str, Any]) -> str:
    card = entry.get("card", {})
    mana_cost = card.get("mana_cost", "")
    type_line = card.get("type_line", "")
    prices = card.get("prices", {})
    usd = _format_usd(prices.get("usd"))
    return f"- {quantity}x **{name}** {mana_cost} — {type_line} [{usd}]"


class SearchDecksInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    query: str = Field(..., description="Free-text search query, e.g. 'atraxa infect budget'.", min_length=1, max_length=300)
    format: Optional[str] = Field(default=None, description="Filter by format, e.g. 'commander', 'modern', 'standard'. Optional.")
    page: Optional[int] = Field(default=1, ge=1, le=100, description="Page number of results (default 1).")
    page_size: Optional[int] = Field(default=10, ge=1, le=50, description="Results per page (default 10, max 50).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("format")
    @classmethod
    def lowercase_format(cls, v: Optional[str]) -> Optional[str]:
        return v.lower().strip() if v else v


class GetDeckInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    deck_url_or_id: str = Field(
        ...,
        description=(
            "The deck's Moxfield public URL (e.g. 'https://moxfield.com/decks/F62pAiveVUGu9D3pIwFsnA') "
            "or just the publicId string (e.g. 'F62pAiveVUGu9D3pIwFsnA')."
        ),
        min_length=1,
        max_length=300,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SearchCardsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    query: str = Field(..., description="Card name or keyword to search for, e.g. 'Sol Ring' or 'draw a card'.", min_length=1, max_length=300)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


@mcp.tool(
    name="moxfield_search_decks",
    annotations={
        "title": "Search Moxfield Public Decklists",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def moxfield_search_decks(params: SearchDecksInput) -> str:
    """Search for public decklists on Moxfield.

    Use this to discover existing decklists matching a commander, theme, or
    strategy — e.g. "atraxa infect", "budget dockside", "cEDH consultation".
    Returns deck name, format, author, like/view counts, and a link.

    Args:
        params (SearchDecksInput): Validated input containing:
            - query (str): Free-text search, e.g. 'atraxa proliferate'
            - format (Optional[str]): Filter by format, e.g. 'commander'
            - page (int): Page number (default 1)
            - page_size (int): Results per page, 1-50 (default 10)
            - response_format (ResponseFormat): 'markdown' or 'json'

    Returns:
        str: Markdown list of matching decks with metadata and URLs, or JSON:
        {"total": int, "decks": [ <deck summary>, ... ]}

        Error response: "Error: <message>"

    Examples:
        - "Find Commander decks for Atraxa" -> query="atraxa", format="commander"
        - "Show me cEDH decks" -> query="cEDH"
        - Don't use when the user has a specific deck URL (use moxfield_get_deck).
    """
    try:
        api_params: Dict[str, Any] = {
            "q": params.query,
            "pageNumber": params.page,
            "pageSize": params.page_size,
        }
        if params.format:
            api_params["fmt"] = params.format

        data = await _get("v2/decks/search", params=api_params)
        decks = data.get("data", [])
        total = data.get("totalResults", 0)

        if not decks:
            return f"No decks found matching '{params.query}'."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"total": total, "decks": decks}, indent=2)

        lines = [f"# Moxfield deck search: `{params.query}`", ""]
        lines.append(f"{total} total result(s), showing page {params.page} ({len(decks)} decks)")
        lines.append("")
        for deck in decks:
            name = deck.get("name", "Unknown")
            fmt = deck.get("format", "")
            author = deck.get("createdByUser", {}).get("displayName", "?")
            likes = deck.get("likeCount", 0)
            views = deck.get("viewCount", 0)
            url = deck.get("publicUrl", "")
            hubs = ", ".join(deck.get("hubNames", []))
            lines.append(f"### [{name}]({url})")
            lines.append(f"By **{author}** · {fmt} · {likes} likes · {views} views")
            if hubs:
                lines.append(f"Tags: {hubs}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return _handle_api_error(e, "moxfield_search_decks")


@mcp.tool(
    name="moxfield_get_deck",
    annotations={
        "title": "Get Moxfield Deck Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def moxfield_get_deck(params: GetDeckInput) -> str:
    """Fetch a specific Moxfield deck's full card list, commander, and stats.

    Use this when you have a Moxfield deck URL or publicId and want to
    inspect its cards (mainboard, commanders, sideboard), mana costs, prices,
    type distribution, and legality.

    Args:
        params (GetDeckInput): Validated input containing:
            - deck_url_or_id (str): Full Moxfield URL or the publicId string
            - response_format (ResponseFormat): 'markdown' or 'json'

    Returns:
        str: Markdown decklist grouped by board (Commanders, Mainboard, etc.)
        with mana cost, type line, and USD price per card, or the raw JSON deck object.

        Error response: "Error: <message>" (e.g. deck not found or private)

    Examples:
        - "Show me this deck: https://moxfield.com/decks/F62pAiveVUGu9D3pIwFsnA"
          -> deck_url_or_id="https://moxfield.com/decks/F62pAiveVUGu9D3pIwFsnA"
        - Don't use for searching by topic (use moxfield_search_decks).
    """
    try:
        public_id = _extract_public_id(params.deck_url_or_id)
        deck = await _get(f"v2/decks/all/{public_id}")

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(deck, indent=2)

        name = deck.get("name", "Unknown")
        fmt = deck.get("format", "")
        author = deck.get("createdByUser", {}).get("displayName", "?")
        url = deck.get("publicUrl", "")
        is_legal = deck.get("isLegal", None)
        legal_str = " ✅ (legal)" if is_legal else " ❌ (not legal)" if is_legal is False else ""
        lines = [f"# [{name}]({url})", ""]
        lines.append(f"**Format**: {fmt}{legal_str} · **By**: {author}")
        lines.append("")

        def _board_section(title: str, board: Dict[str, Any]) -> List[str]:
            if not board:
                return []
            section = [f"## {title}"]
            for card_name, entry in sorted(board.items()):
                qty = entry.get("quantity", 1)
                section.append(_card_line_md(card_name, qty, entry))
            section.append("")
            return section

        for board_key, board_title in [
            ("commanders", "Commanders"),
            ("mainboard", "Mainboard"),
            ("sideboard", "Sideboard"),
            ("maybeboard", "Maybeboard"),
        ]:
            lines.extend(_board_section(board_title, deck.get(board_key, {})))

        return "\n".join(lines)
    except Exception as e:
        return _handle_api_error(e, "moxfield_get_deck")


@mcp.tool(
    name="moxfield_search_cards",
    annotations={
        "title": "Search Moxfield Card Database",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def moxfield_search_cards(params: SearchCardsInput) -> str:
    """Search Moxfield's card database for cards by name or keyword.

    Returns card data including mana cost, type, oracle text, legalities, and
    prices (USD, EUR, MTGO tix, CardKingdom, etc.). Prices are Moxfield's
    own aggregated buy/sell data, so this is a convenient one-stop shop for
    current market prices.

    Args:
        params (SearchCardsInput): Validated input containing:
            - query (str): Card name or keyword, e.g. 'Sol Ring' or 'Counterspell'
            - response_format (ResponseFormat): 'markdown' or 'json'

    Returns:
        str: Markdown summary of matching cards (up to 10 shown) with price
        data and legalities, or JSON: {"total": int, "cards": [...]}

        Error response: "Error: <message>"

    Examples:
        - "What's Sol Ring worth?" -> query="Sol Ring"
        - "Find all cards named like 'Counterspell'" -> query="counterspell"
        - Don't use for searching decklists (use moxfield_search_decks).
    """
    try:
        data = await _get("v2/cards/search", params={"q": params.query})
        cards = data.get("data", [])
        total = data.get("totalCards", len(cards))

        if not cards:
            return f"No cards found matching '{params.query}'."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"total": total, "cards": cards}, indent=2)

        lines = [f"# Moxfield card search: `{params.query}`", ""]
        lines.append(f"{total} result(s)")
        lines.append("")
        for card in cards[:10]:
            card_name = card.get("name", "Unknown")
            mana_cost = card.get("mana_cost", "")
            type_line = card.get("type_line", "")
            oracle = card.get("oracle_text", "")
            prices = card.get("prices", {})
            usd = _format_usd(prices.get("usd"))
            eur = _format_usd(prices.get("eur"))
            ck = _format_usd(prices.get("ck"))
            lines.append(f"## {card_name} {mana_cost}".rstrip())
            lines.append(f"*{type_line}*")
            if oracle:
                lines.append("")
                lines.append(oracle)
            lines.append(f"\n**Prices**: USD {usd} · EUR {eur} · CK {ck}")
            if card.get("legalities"):
                legal_formats = [k for k, v in card["legalities"].items() if v == "legal"]
                lines.append(f"**Legal in**: {', '.join(legal_formats[:8])}" + (" …" if len(legal_formats) > 8 else ""))
            lines.append("")
        if total > 10:
            lines.append(f"_Showing 10 of {total}. Refine the query for more specific results._")
        return "\n".join(lines)
    except Exception as e:
        return _handle_api_error(e, "moxfield_search_cards")


if __name__ == "__main__":
    if os.environ.get("PORT"):
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
