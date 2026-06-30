# Moxfield MCP Server

A local MCP server that gives Claude access to Moxfield's deckbuilding platform data — public deck search, deck card lists, and card prices.

Moxfield has no official public API. This server calls the same JSON endpoints (`api2.moxfield.com`) that moxfield.com's own frontend uses. These endpoints are **undocumented and unofficial** — they may change or break without notice. No API key is needed; requests include browser-like headers to satisfy Cloudflare.

## Tools

- `moxfield_search_decks` — search public decklists by keyword, optionally filtered by format; returns deck names, authors, like/view counts, and URLs
- `moxfield_get_deck` — fetch a specific deck's full card list (commanders, mainboard, sideboard) with mana costs, type lines, and per-card USD prices
- `moxfield_search_cards` — search Moxfield's card database by name or keyword, returning oracle text, legalities, and prices from multiple vendors

## Setup

### 1. Install dependencies

Requires Python 3.10+.

```
cd "moxfield_mcp"
pip install -r requirements.txt
```

### 2. Test it directly (optional)

```
python server.py
```

With no `PORT` environment variable set, this runs over stdio (for the MCP Inspector or a classic Claude Desktop config). You can also exercise it with the MCP Inspector:

```
npx @modelcontextprotocol/inspector python server.py
```

### 3. Register it as a connector in Cowork (this project)

Cowork's "Add custom connector" dialog only accepts a remote MCP server URL — it can't point at a local script. `server.py` runs over streamable-HTTP automatically whenever a `PORT` environment variable is present (which is how Render and most PaaS hosts tell an app what to bind to). That's what makes it deployable.

Deploy to Render (free tier):

1. Push the contents of this `moxfield-mcp` folder to a new GitHub repo (the folder's contents should be the repo root — `server.py`, `requirements.txt`, and `render.yaml` at the top level).
   ```
   cd "moxfield-mcp"
   git init
   git add .
   git commit -m "Moxfield MCP server"
   git branch -M main
   git remote add origin https://github.com/<your-username>/moxfield-mcp.git
   git push -u origin main
   ```
2. Go to render.com → sign in with GitHub → New → Blueprint → select your `moxfield-mcp` repo. Render will read `render.yaml` and configure the service automatically. Click Apply.
3. Wait for the first deploy to finish (a few minutes). Render gives you a URL like `https://moxfield-mcp.onrender.com`.
4. Sanity-check it's alive by visiting `https://moxfield-mcp.onrender.com/mcp` in a browser — a 4xx/JSON error about missing headers is fine; that means the MCP endpoint is up.
5. In Cowork, open Settings → Connectors → Add custom connector, and paste:
   - Name: Moxfield (or anything you like)
   - Remote MCP server URL: `https://moxfield-mcp.onrender.com/mcp`
   - Leave Advanced settings (OAuth) blank — this server has no auth.
6. Save. The Moxfield tools should now show up as a connector you can enable in any conversation.

Note on the free tier: Render's free web services spin down after ~15 minutes of inactivity and take 30-60 seconds to wake back up on the next request (cold start).

## Notes

- Moxfield's API is Cloudflare-protected. This server mimics browser headers to bypass the bot check — this may break if Moxfield changes their Cloudflare configuration.
- Private/unlisted decks will return a 404 error; only public decks are accessible without authentication.
- Prices are Moxfield's aggregated vendor data and update daily.
