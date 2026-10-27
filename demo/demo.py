"""Terminal demo: a real MCP client talking to the Paperasse server over stdio.

Recorded with VHS (demo/demo.tape). The tool calls and their results are
real. The step an assistant would do itself, turning the user's question
into French keywords as the search_fiche docstring asks, is written in this
script and labelled as such on screen.

Run: uv run python demo/demo.py   (needs data/paperasse.db)
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
PACE = float(os.environ.get("DEMO_PACE", "1"))  # 0 for a fast run

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
BLUE, GREEN, YELLOW, RED, CYAN = "\033[34m", "\033[32m", "\033[33m", "\033[31m", "\033[36m"


def say(text: str = "", pause: float = 0.6) -> None:
    print(text, flush=True)
    time.sleep(pause * PACE)


def typed(prefix: str, text: str) -> None:
    sys.stdout.write(prefix)
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.03 * PACE)
    say("", 0.8)


async def call(session: ClientSession, tool: str, **args) -> dict:
    shown = ", ".join(f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}" for k, v in args.items())
    say(f"{CYAN}  → appel MCP : {tool}({shown}){RESET}", 1.0)
    result = await session.call_tool(tool, args)
    if result.is_error:
        return {"error": result.content[0].text}
    return json.loads(result.content[0].text)


def show_results(out: dict, n: int = 3) -> None:
    for i, r in enumerate(out["results"][:n], 1):
        say(f"    {i}. {BOLD}{r['title']}{RESET}  {DIM}(match {r['match']}){RESET}", 0.4)
        say(f"       {BLUE}{r['url']}{RESET}  · mis à jour le {r['updated_at']}", 0.5)
    flag = f"{RED}true{RESET}" if out["low_confidence"] else f"{GREEN}false{RESET}"
    say(f"    low_confidence: {flag}", 1.2)


def show_fiche(fiche: dict, lines: int = 6) -> None:
    say(f"{CYAN}  ← texte officiel, tel quel (extrait) :{RESET}", 0.6)
    body = [ln for ln in fiche["text"].splitlines() if ln.strip()][:lines]
    for ln in body:
        say(f"    {DIM}│{RESET} {ln[:110]}{'…' if len(ln) > 110 else ''}", 0.35)
    say(f"    {GREEN}Source : {fiche['url']} — mise à jour le {fiche['updated_at']}{RESET}", 0.4)
    say(f"    {DIM}{fiche['source']}{RESET}", 2.0)


def question(n: int, text: str) -> None:
    say()
    say(f"{BOLD}── {n}/3 ─────────────────────────────────────────────────────────────{RESET}", 0.3)
    typed(f"{BOLD}{YELLOW}Utilisateur :{RESET} ", text)


def assistant_query(query: str, note: str = "") -> None:
    say(f"{DIM}  [assistant, écrit pour la démo] mots-clés officiels : « {query} »{RESET}", 1.0 if not note else 0.4)
    if note:
        say(f"{DIM}  {note}{RESET}", 1.0)


async def main() -> None:
    say(f"{BOLD}Paperasse MCP{RESET} — démarches administratives françaises, sources officielles uniquement", 0.3)
    say(f"{DIM}Outil indépendant, non affilié à l'administration. Contenu : Service-Public.gouv.fr / DILA "
        f"(Licence Ouverte).{RESET}", 0.3)
    say(f"{DIM}Client MCP réel → serveur paperasse (stdio). Seule la reformulation en mots-clés est scriptée.{RESET}", 2.0)

    params = StdioServerParameters(command="uv", args=["run", "main.py"], cwd=ROOT)
    with open(os.devnull, "w") as quiet:
        async with stdio_client(params, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                question(1, "Je suis étudiant, est-ce que j'ai droit aux APL ?")
                assistant_query("APL étudiant")
                out = await call(session, "search_fiche", query="APL étudiant", limit=3)
                show_results(out)
                show_fiche(await call(session, "get_fiche", id=out["results"][0]["id"]))

                question(2, "How do I declare my auto-entrepreneur revenue to URSSAF?")
                assistant_query("auto-entrepreneur déclarer chiffre d'affaires URSSAF",
                                "(le serveur ajoute le synonyme officiel : auto-entrepreneur → micro-entrepreneur)")
                out = await call(session, "search_fiche",
                                 query="auto-entrepreneur déclarer chiffre d'affaires URSSAF", limit=3)
                show_results(out)
                say(f"{DIM}  low_confidence : la consigne de l'outil dit de réessayer avec les termes officiels.{RESET}", 1.2)
                assistant_query("micro-entrepreneur déclaration chiffre d'affaires")
                out = await call(session, "search_fiche", query="micro-entrepreneur déclaration chiffre d'affaires",
                                 limit=3)
                show_results(out)
                best = max(out["results"][:3], key=lambda r: r["match"])
                say(f"{DIM}  L'assistant lit la fiche dont le titre couvre la question (match {best['match']}).{RESET}", 1.0)
                show_fiche(await call(session, "get_fiche", id=best["id"]))

                question(3, "Quelle est la meilleure recette de crêpes ?")
                assistant_query("recette crêpes")
                out = await call(session, "search_fiche", query="recette crêpes", limit=3)
                show_results(out)
                say(f"{YELLOW}  hint : {out.get('hint', '')}{RESET}", 1.0)
                say(f"{BOLD}  → L'assistant répond qu'il n'a trouvé aucun guide officiel sur ce sujet.{RESET}", 2.5)

    say()
    say(f"{BOLD}github.com/medkouritahaparis-create/paperasse-mcp{RESET}  ·  MIT  ·  "
        f"non affilié à l'administration", 3.0)


if __name__ == "__main__":
    asyncio.run(main())
