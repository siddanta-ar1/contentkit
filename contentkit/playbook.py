"""Planning knowledge: shot lists for real shoots, and hook formulas that stop the scroll.

  contentkit shotlist [hotel|birthday|food|product|real-estate|wedding|event|talking-head]
  contentkit hooks [pov|curiosity|contrarian|story|list|challenge|reaction|local]
  contentkit hooks collect URL ... [--seconds 3]   save just the openings of reference videos
"""
import json
from pathlib import Path

# (shot, framing / move, seconds to roll, why)
SHOTLISTS = {
    "hotel": [
        ("Exterior with sign", "wide, slow push-in, golden hour", 8, "establishes where"),
        ("Arrival: walk through the door", "POV handheld, gimbal if you have one", 6, "puts the viewer there"),
        ("Lobby / reception", "wide, then a detail (bell, flowers, key)", 6, "first impression"),
        ("Room door opening", "POV, open in one move", 4, "the reveal"),
        ("Room wide from the doorway", "wide, level, all lights on", 6, "scale of the room"),
        ("Bed detail", "close-up, slide left-right", 4, "comfort"),
        ("Window view", "walk to window, tilt up to the view", 6, "the 'wow' shot"),
        ("Bathroom", "wide, then shower/amenity detail", 6, "cleanliness"),
        ("Food / breakfast", "top-down + close-up pour or steam", 8, "appetite appeal"),
        ("Pool / rooftop / garden", "wide, then you in it", 8, "lifestyle"),
        ("You talking to camera", "medium, eye level, window light", 30, "opinion + verdict"),
        ("Price / receipt / room card", "insert close-up", 3, "the number people want"),
    ],
    "birthday": [
        ("Venue before guests", "wide, slow move", 6, "sets the scene"),
        ("Decor details", "close-ups: balloons, table, name", 6, "texture"),
        ("Birthday person arriving / surprise", "medium on their face, keep rolling", 10, "the emotion"),
        ("Cake close-up", "macro-ish, candles lit", 4, "the icon of the day"),
        ("Candle blow", "close-up + one wide, 60 fps for slow-mo", 8, "the moment"),
        ("Friends reacting", "close-ups, 3-4 faces", 8, "people tag friends"),
        ("Dancing", "low angle, move with them", 12, "energy for remix cuts"),
        ("Gifts", "hands + face reaction", 8, "payoff beats"),
        ("Group photo", "wide, then everyone cheering", 6, "the ending shot"),
    ],
    "food": [
        ("Signature dish hero", "45° and top-down, side light", 6, "the thumbnail"),
        ("Cooking action", "close-up: sizzle, toss, pour, cheese pull", 10, "motion = appetite"),
        ("Plating", "top-down, hands in frame", 6, "craft"),
        ("First bite", "medium on a face, reaction", 6, "the payoff"),
        ("Menu / price", "insert", 3, "useful info"),
        ("Interior + exterior", "wide", 6, "where to find it"),
    ],
    "product": [
        ("Product hero on clean background", "slow rotate or slide", 6, "thumbnail / end card"),
        ("Unboxing", "top-down hands", 8, "anticipation"),
        ("In use", "medium, real context", 10, "proof it works"),
        ("Detail / texture", "macro", 4, "quality"),
        ("Problem without it", "short, relatable", 4, "the hook"),
        ("Result with it", "same framing as the problem shot", 4, "before/after cut"),
        ("Price / where to buy", "insert or card", 3, "call to action"),
    ],
    "real-estate": [
        ("Exterior / street", "wide, drone if allowed", 8, "location"),
        ("Front door → entry", "gimbal walk-through", 8, "flow"),
        ("Living room", "wide from a corner, lights on, blinds open", 6, "space"),
        ("Kitchen", "wide + counter detail", 6, "most viewed room"),
        ("Bedrooms", "wide from the door", 6, "size"),
        ("Bathroom", "wide", 4, ""),
        ("View / balcony", "walk out, reveal", 6, "the wow"),
        ("Price, size, contact", "card", 3, ""),
    ],
    "wedding": [
        ("Getting ready details", "close-ups: dress, jewellery, shoes", 10, ""),
        ("First look", "two angles if possible", 15, "the emotion"),
        ("Ceremony key moment", "close-up faces + wide", 20, ""),
        ("Family reactions", "close-ups", 10, ""),
        ("Couple portraits", "golden hour, slow motion", 15, "hero shots"),
        ("Dance", "wide + close-up", 20, ""),
        ("Send-off", "wide", 8, "ending"),
    ],
    "event": [
        ("Venue empty → full", "same framing, two times", 6, "transformation cut"),
        ("Entry / signage", "wide", 4, ""),
        ("Speaker / performer", "close-up + wide", 15, ""),
        ("Crowd reactions", "close-ups", 8, "social proof"),
        ("Behind the scenes", "handheld", 8, ""),
        ("Ending moment", "wide", 6, ""),
    ],
    "talking-head": [
        ("Main take", "medium close-up, eyes on lens, window light at 45°", 60, "lav or phone 30 cm away"),
        ("Punch-in safety", "same take, framed tighter or 4K to crop", 0, "for jump-cut punch-ins"),
        ("B-roll for every claim", "3-5 s each, whatever proves the point", 5, "cover jump cuts"),
        ("Reaction / silent beats", "you, no words", 3, "comedy timing"),
    ],
}

GENERAL_SHOOT_RULES = [
    "Shoot vertical (9:16) for Reels/TikTok/Shorts; 4K if the phone allows, so you can punch in.",
    "Clean the lens. Lock exposure/focus on the subject (long-press on phones).",
    "Light from a window at 45°; never with the window behind the subject.",
    "Hold every shot 3 s longer than you think: the edit needs handles.",
    "Record 10 s of room tone and every sound you might want (door, pour, laugh).",
    "Get one shot of each person looking straight at the lens: it is the strongest hook frame.",
]

HOOKS = {
    "pov": ["POV: {situation}", "POV: you {did the thing} and {unexpected result}",
            "When {relatable situation} but {twist}"],
    "curiosity": ["Nobody talks about {thing}", "I wasn't supposed to show you this, but {thing}",
                  "Watch till the end: {promise}", "The {place} nobody in {city} knows about"],
    "contrarian": ["Stop {common habit}. Do this instead", "{Popular thing} is overrated. Here's why",
                   "You've been {doing X} wrong"],
    "story": ["I {did something bold} and here's what happened", "Day 1 of {challenge}",
              "This {person/place} changed how I {verb}"],
    "list": ["3 {things} in {city} under {price}", "{N} things I wish I knew before {event}",
             "Rating every {thing} in {place}"],
    "challenge": ["Can I {do X} with only {constraint}?", "{Price} vs {price}: which is worth it?",
                  "I tried the viral {thing} so you don't have to"],
    "reaction": ["Wait for it…", "The way {person} {reacted}", "I was not ready for {thing}"],
    "local": ["Kathmandu people will understand", "Only Nepalis will get this",
              "{Place} at {time} hits different"],
}

HOOK_RULES = [
    "Frame 1 already shows the subject (a face or the thing) and the hook text: no logo, no intro.",
    "Text on frame 1 because most people start muted; keep it under ~8 words.",
    "First cut by ~1 s; the payoff before the end; no outro card after the payoff.",
    "Specific beats generic: a place, a price, a number, a name.",
    "Ask a real question in the caption ('Which one are you?'); never 'tag a friend' or 'comment YES'"
    " (engagement bait is demoted).",
]


def shotlist_md(kind):
    if kind not in SHOTLISTS:
        raise SystemExit(f"Unknown shoot type '{kind}'. Choose from: {', '.join(SHOTLISTS)}")
    lines = [f"# Shot list: {kind}", "", "| # | Shot | Framing / move | Roll (s) | Why |", "|---|---|---|---|---|"]
    for i, (shot, how, secs, why) in enumerate(SHOTLISTS[kind], 1):
        lines.append(f"| {i} | {shot} | {how} | {secs or '-'} | {why} |")
    lines += ["", "## Every shoot", ""] + [f"- [ ] {r}" for r in GENERAL_SHOOT_RULES]
    return "\n".join(lines) + "\n"


def hooks_md(category=None):
    cats = [category] if category else list(HOOKS)
    lines = ["# Hook formulas", ""]
    for c in cats:
        if c not in HOOKS:
            raise SystemExit(f"Unknown hook category '{c}'. Choose from: {', '.join(HOOKS)}")
        lines += [f"## {c}", ""] + [f"- {h}" for h in HOOKS[c]] + [""]
    lines += ["## Rules", ""] + [f"- {r}" for r in HOOK_RULES]
    return "\n".join(lines) + "\n"


HOOK_LIBRARY = Path.home() / ".contentkit" / "hooks"


def collect(urls, seconds=3.0, browser=None, log=print):
    """Save the first `seconds` of each video plus its hook-frame analysis, to study what
    makes openings work. Private study material: rebuild the idea with your own footage."""
    from . import vision
    from .fetch import download
    HOOK_LIBRARY.mkdir(parents=True, exist_ok=True)
    index = HOOK_LIBRARY / "index.json"
    items = json.loads(index.read_text()) if index.exists() else []
    for url in urls:
        path, meta = download(url, out_dir=HOOK_LIBRARY, start=0, end=seconds, browser=browser)
        frame = vision.frame_at(path, min(0.3, seconds / 3))
        tx, fc = vision.text(frame), vision.faces(frame)
        entry = {"file": str(path), "url": meta.get("url"), "title": meta.get("title"),
                 "uploader": meta.get("uploader"), "hook_text": (tx or {}).get("text") or None,
                 "framing": vision.framing(fc) if fc is not None else None}
        items = [e for e in items if e["file"] != entry["file"]] + [entry]
        log(f"  {entry['title']}  |  text: {entry['hook_text'] or '-'}  |  {entry['framing']}")
    index.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    return items
