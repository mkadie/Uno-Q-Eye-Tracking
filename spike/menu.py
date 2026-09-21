"""Reader for T-Rex Talker `.menu` files.

The talker's menus are INI-ish text that teachers and parents edit by hand --
`name = value`, `[section]` headers, `#` comments. That format is deliberate
(see talker_v3/docs/menu_system.md) and this reader exists so the gaze demo
speaks the SAME vocabulary as the real device rather than an invented one. A
demo with different words is not a test of anything.

Deliberately tolerant: an unknown key is kept, not rejected, because the
device's own reader will grow keys this one has never heard of and a gaze demo
must not be the reason a teacher's menu file stops loading.
"""

import os
import re


class Press(object):
    """One selectable cell."""

    def __init__(self, key, fields):
        self.key = key
        self.fields = dict(fields)
        self.label = fields.get("label", key)
        self.text = fields.get("text_description", self.label)
        self.sound = fields.get("sound")
        self.image = fields.get("image")
        self.submenu = fields.get("submenu")
        try:
            self.position = int(fields.get("position", 0))
        except ValueError:
            self.position = 0

    @property
    def is_submenu(self):
        return bool(self.submenu)

    def __repr__(self):
        return "Press(%r, pos=%d%s)" % (
            self.label, self.position, ", submenu" if self.submenu else "")


class Menu(object):
    """A grid of presses, ordered by `position` (1-based, row-major)."""

    def __init__(self, name, columns, rows, presses, path=None, fields=None):
        self.name = name
        self.columns = int(columns)
        self.rows = int(rows)
        self.path = path
        self.fields = dict(fields or {})
        self.presses = sorted(presses, key=lambda p: p.position)

    @property
    def capacity(self):
        return self.columns * self.rows

    def at(self, col, row):
        """Press at a grid cell, or None. Positions are 1-based row-major."""
        pos = row * self.columns + col + 1
        for p in self.presses:
            if p.position == pos:
                return p
        return None

    def __repr__(self):
        return "Menu(%r, %dx%d, %d presses)" % (
            self.name, self.columns, self.rows, len(self.presses))


_SECTION = re.compile(r"^\[(.+?)\]\s*$")


def parse(text, path=None):
    """Parse menu text. Returns a Menu."""
    section = None
    fields = {}
    order = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip()
            if section not in fields:
                fields[section] = {}
                order.append(section)
            continue
        if "=" not in line or section is None:
            continue
        k, v = line.split("=", 1)
        fields[section][k.strip()] = v.strip()

    meta = fields.get("menu", {})
    presses = [Press(k, fields[k]) for k in order if k != "menu"]

    # Position is what places a cell, so a menu that omits it is ambiguous.
    # Fall back to file order rather than refusing -- but do it explicitly,
    # because silently stacking every press on cell 1 is the kind of failure
    # that looks like a rendering bug.
    for i, p in enumerate(presses):
        if p.position <= 0:
            p.position = i + 1

    return Menu(
        name=meta.get("name", os.path.basename(path or "menu")),
        columns=int(meta.get("columns", 3)),
        rows=int(meta.get("rows", 2)),
        presses=presses,
        path=path,
        fields=meta,
    )


def load(path):
    with open(path, "r") as fh:
        return parse(fh.read(), path=path)


def resolve(ref, base_dir):
    """Resolve a `submenu =` reference against the menu directory."""
    if not ref:
        return None
    if os.path.isabs(ref):
        return ref
    return os.path.join(base_dir, ref)
