"""A person names groups of sightings on a page; the names go back into a manifest.

On a user's farm this is enrolment. On a test farm it is also how the later days
get their labels: their sightings are grouped and named the same way, so `enroll`
can score them.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from reid.enrollment import cut, merge_tree, sighting_vectors, sightings
from reid.local import spread
from reid.manifest import Crop
from reid.matching import similarities

THUMBNAIL = 160


def group_sightings(
    crops: Sequence[Crop], vectors: NDArray[np.float32], merge: float
) -> tuple[list[list[int]], list[int]]:
    """Every sighting in the manifest, and its group at similarity `merge`."""
    seen = sightings(crops, range(len(crops)))
    means = sighting_vectors(vectors, seen)
    return seen, cut(merge_tree(similarities(means, means)), len(seen), merge).tolist()


def write_page(
    crops: Sequence[Crop],
    seen: Sequence[Sequence[int]],
    groups: Sequence[int],
    out: Path,
    per_group: int = 12,
) -> int:
    """Write `index.html`, its thumbnails and `groups.csv` to `out`.

    Groups with the most sightings come first, as on a farm. Each shows up to
    `per_group` sightings spread over time, one picture each; sightings not shown
    take the group's name. Returns the number of groups.
    """
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    members: dict[int, list[int]] = {}
    for sighting, group in enumerate(groups):
        members.setdefault(group, []).append(sighting)
    order = sorted(
        members,
        key=lambda group: (
            -len(members[group]),
            -sum(len(seen[sighting]) for sighting in members[group]),
            group,
        ),
    )
    cards = []
    numbers = {}
    for number, group in enumerate(order, start=1):
        numbers[group] = number
        ordered = sorted(members[group], key=lambda s: crops[seen[s][0]].session)
        shown = spread(ordered, per_group)
        hidden = sorted(set(ordered) - set(shown), key=ordered.index)
        for sighting in shown:
            middle = crops[seen[sighting][len(seen[sighting]) // 2]]
            with Image.open(middle.path) as picture:
                picture = picture.convert("RGB")
                picture.thumbnail((THUMBNAIL, THUMBNAIL))
                picture.save(thumbs / f"{sighting}.jpg", quality=85)
        cards.append(
            {
                "group": number,
                "sessions": sorted({crops[seen[s][0]].session for s in ordered}),
                "shown": [
                    {"id": s, "session": crops[seen[s][0]].session} for s in shown
                ],
                "hidden": hidden,
            }
        )
    with (out / "groups.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("path", "sighting", "group"))
        for sighting, (indices, group) in enumerate(zip(seen, groups, strict=True)):
            for index in indices:
                writer.writerow(
                    (crops[index].path.resolve().as_posix(), sighting, numbers[group])
                )
    data = json.dumps(cards, separators=(",", ":")).replace("</", "<\\/")
    (out / "index.html").write_text(
        PAGE.replace("/*CARDS*/[]", data).replace(
            "/*KEY*/", json.dumps(str(out.resolve()))
        ),
        encoding="utf-8",
    )
    return len(order)


def apply_names(crops: Sequence[Crop], groups: Path, names: Path) -> list[Crop]:
    """The crops of named sightings, each with its sighting's name as identity.

    `groups` is the page's `groups.csv`, `names` the `names.csv` it downloads.
    Crops of sightings left unnamed or left out are dropped.
    """
    with groups.open(newline="", encoding="utf-8") as file:
        sighting_of = {row["path"]: row["sighting"] for row in csv.DictReader(file)}
    with names.open(newline="", encoding="utf-8") as file:
        name_of = {
            row["sighting"]: row["name"].strip()
            for row in csv.DictReader(file)
            if row["name"].strip()
        }
    named = []
    for crop in crops:
        sighting = sighting_of.get(crop.path.resolve().as_posix())
        if sighting in name_of:
            named.append(replace(crop, identity=name_of[sighting]))
    return named


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Name the cows</title>
<style>
:root { color-scheme: light dark; --bg: #fafaf7; --card: #fff; --text: #1d1d1b;
  --muted: #6b6b66; --line: #deded8; --accent: #2f6f4e; --out: #b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --card: #20201e; --text: #ecece6; --muted: #a3a39c;
    --line: #34342f; --accent: #7cc49b; --out: #f2b8b5; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 1; background: var(--bg);
  border-bottom: 1px solid var(--line); padding: 12px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
header p { margin: 4px 0; color: var(--muted); max-width: 70ch; }
.bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
button { font: inherit; padding: 6px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--accent); background: var(--accent); color: var(--bg); }
main { padding: 16px; display: grid; gap: 12px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; }
.card.named { border-color: var(--accent); }
.head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.head h2 { font-size: 15px; margin: 0; }
.head span { color: var(--muted); }
.head input { font: inherit; width: 9em; padding: 4px 8px; margin-left: auto;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg);
  color: var(--text); }
.thumbs { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.thumbs figure { margin: 0; cursor: pointer; position: relative; }
.thumbs img { display: block; height: 110px; border-radius: 4px; }
.thumbs figcaption { font-size: 11px; color: var(--muted); }
.thumbs figure.out img { opacity: 0.3; outline: 3px solid var(--out); }
.more { color: var(--muted); font-size: 13px; align-self: center; }
</style>
</head>
<body>
<header>
<h1>Name the cows</h1>
<p>Each card is one group of sightings that look alike, the biggest first. Type the
cow's number and press Enter; leave it empty to skip a group. Click a picture of a
different cow to leave that sighting out.</p>
<div class="bar"><button id="download">Download names</button>
<span id="progress"></span></div>
</header>
<main id="groups"></main>
<script>
const CARDS = /*CARDS*/[];
const KEY = "reid-names:" + /*KEY*/;
let state = { names: {}, out: [] };
try { state = JSON.parse(localStorage.getItem(KEY)) || state; } catch (error) {}
const out = new Set(state.out);
function save() {
  state.out = [...out];
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (error) {}
  const named = CARDS.filter((card) => state.names[card.group]);
  const count = named.reduce((sum, card) => sum + card.hidden.length +
    card.shown.filter((sighting) => !out.has(sighting.id)).length, 0);
  document.getElementById("progress").textContent =
    `${named.length} of ${CARDS.length} groups named, ${count} sightings`;
}
const main = document.getElementById("groups");
CARDS.forEach((card, position) => {
  const element = document.createElement("section");
  element.className = "card";
  const head = document.createElement("div");
  head.className = "head";
  const title = document.createElement("h2");
  title.textContent = `Group ${card.group}`;
  const about = document.createElement("span");
  const total = card.shown.length + card.hidden.length;
  about.textContent = `${total} sighting${total === 1 ? "" : "s"} · ` +
    card.sessions.join(", ");
  const input = document.createElement("input");
  input.placeholder = "Cow number";
  input.value = state.names[card.group] || "";
  element.classList.toggle("named", Boolean(input.value));
  input.addEventListener("input", () => {
    const name = input.value.trim();
    if (name) state.names[card.group] = name; else delete state.names[card.group];
    element.classList.toggle("named", Boolean(name));
    save();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const next = main.querySelectorAll("input")[position + 1];
    if (next) { next.focus(); next.scrollIntoView({ block: "center" }); }
  });
  head.append(title, about, input);
  const thumbs = document.createElement("div");
  thumbs.className = "thumbs";
  card.shown.forEach((sighting) => {
    const figure = document.createElement("figure");
    figure.classList.toggle("out", out.has(sighting.id));
    const image = document.createElement("img");
    image.src = `thumbs/${sighting.id}.jpg`;
    image.loading = "lazy";
    image.alt = `Sighting ${sighting.id}`;
    const caption = document.createElement("figcaption");
    caption.textContent = sighting.session;
    figure.append(image, caption);
    figure.addEventListener("click", () => {
      if (out.has(sighting.id)) out.delete(sighting.id); else out.add(sighting.id);
      figure.classList.toggle("out", out.has(sighting.id));
      save();
    });
    thumbs.append(figure);
  });
  if (card.hidden.length) {
    const more = document.createElement("span");
    more.className = "more";
    more.textContent = `+${card.hidden.length} more, named with the group`;
    thumbs.append(more);
  }
  element.append(head, thumbs);
  main.append(element);
});
document.getElementById("download").addEventListener("click", () => {
  const rows = ["sighting,name"];
  CARDS.forEach((card) => {
    const name = state.names[card.group];
    if (!name) return;
    const clean = name.replaceAll('"', '""');
    [...card.shown.map((s) => s.id), ...card.hidden].forEach((id) => {
      if (!out.has(id)) rows.push(`${id},"${clean}"`);
    });
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([rows.join("\\n") + "\\n"],
    { type: "text/csv" }));
  link.download = "names.csv";
  link.click();
});
save();
</script>
</body>
</html>
"""
