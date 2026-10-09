"""remeasure.py — which scheduled power re-measurements are due (configs/remeasure.yml).

Until 2026-10-09 "re-measure yearly" lived in report prose (INSIDER_POWER.md,
0076) and nothing would ever say it again. The digest now lists an item from
`warn_days` before its due date until `last_done` is moved past it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import yaml

from src.common.paths import CONFIGS

PATH = CONFIGS / "remeasure.yml"


@dataclass(frozen=True)
class Item:
    id: str
    what: str
    due: date
    last_done: date
    command: str

    def state(self, today: date, warn_days: int) -> str | None:
        """'OVERDUE', 'DUE SOON' or None. Done once last_done reaches due."""
        if self.last_done >= self.due:
            return None
        if today >= self.due:
            return "OVERDUE"
        if (self.due - today).days <= warn_days:
            return "DUE SOON"
        return None


def load(path=PATH) -> tuple[list[Item], int]:
    cfg = yaml.safe_load(path.read_text())
    items = [Item(i["id"], i["what"], i["due"], i["last_done"], i["command"]) for i in cfg["items"]]
    return items, int(cfg["warn_days"])


def lines(today: date, path=PATH) -> list[str]:
    """Digest lines: every item, flagged when due."""
    items, warn = load(path)
    out = []
    for it in sorted(items, key=lambda i: i.due):
        st = it.state(today, warn)
        flag = f"{st:<9}" if st else "ok       "
        out.append(f"  {flag}{it.id:<24} due {it.due}  ({it.what})")
        if st:
            out.append(f"           run: {it.command}")
    return out
