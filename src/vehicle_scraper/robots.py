"""robots.txt rules with `*` and `$` wildcards (RFC 9309).

`urllib.robotparser` matches rule paths as plain prefixes, so a rule like
`Disallow: /used-cars-for-sale/listing/*` never matches anything and the site's
wish is silently ignored. This parser follows RFC 9309 instead:
* the group for our product token wins over `*`; groups for the same agent are merged;
* `*` matches any run of characters, a trailing `$` anchors the end of the URL;
* the longest matching rule wins, and `Allow` wins a tie with `Disallow`.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlparse


class RobotsRules:
    def __init__(self, text: str, user_agent: str):
        self.token = user_agent.split("/")[0].strip().lower()
        groups: list[tuple[list[str], list[tuple[bool, str]], Optional[float]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: Optional[float] = None
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:                         # a new group starts
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(value.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if agents and value:                 # empty Disallow = allow everything
                    rules.append((key == "allow", value))
            elif key == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))

        mine = [g for g in groups if any(a != "*" and a in self.token for a in g[0])]
        chosen = mine or [g for g in groups if "*" in g[0]]
        self.rules = [r for g in chosen for r in g[1]]
        delays = [g[2] for g in chosen if g[2] is not None]
        self.crawl_delay: Optional[float] = max(delays) if delays else None
        self._compiled = [(allow, len(path), _pattern(path)) for allow, path in self.rules]

    def can_fetch(self, url: str) -> bool:
        p = urlparse(url)
        target = unquote(p.path or "/") + (f"?{unquote(p.query)}" if p.query else "")
        best: Optional[tuple[int, bool]] = None          # (rule length, allow)
        for allow, length, rx in self._compiled:
            if rx.match(target) and (best is None or (length, allow) > best):
                best = (length, allow)
        return True if best is None else best[1]


def _pattern(path: str) -> re.Pattern:
    anchored = path.endswith("$")
    body = unquote(path[:-1] if anchored else path)
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(rx + ("$" if anchored else ""))
