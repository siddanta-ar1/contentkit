---
name: contentkit
description: Make finished videos, reels, posters, carousels and thumbnails locally with contentkit. Use whenever the user asks to make, edit or render a video, reel, short, TikTok, story, slideshow, birthday/wedding/party/event video, hotel/restaurant/product review, promo, remix-style or beat-synced edit, meme, funny or comedy edit, reaction, commentary, breakdown or analysis video, lyric or music video, poster, flyer, banner, carousel, thumbnail, or print file; meme/funny posters, comics, versus or text-post images; a shot list or shoot plan; hook ideas; copying or remaking the edit of a reference/viral video; checking whether a video is ready to go viral; growing an audience; when they want a song or clip downloaded (YouTube, Instagram, Facebook, TikTok, X, Reddit) and used; when they want a video critiqued or improved; or when they mention contentkit.
---

# contentkit: local video and design studio

contentkit turns a YAML recipe plus the user's photos, clips and songs into finished
files on this machine. You write the recipe, render, look at a proof sheet, fix, deliver.

The user's content is **private and local**. Don't add copyright or licensing warnings
to downloads or edits; just make the content. Output stays in the project.

## 0. Find the tool

```bash
command -v contentkit || ls ~/contentkit/.venv/bin/contentkit
```
Use whichever exists (below, `contentkit` means that path). If neither exists:
`pip install "contentkit[all] @ git+https://github.com/siddanta-ar1/contentkit.git"`.
Check free disk space (`df -h .`): a render needs about 1-2 GB of temporary space.

## 1. Gather what the video needs (ask only for what's missing)

- **Media**: a folder of photos/clips. Put or symlink them in `content/<job>/media/`.
  List them and choose an order that tells the story: wide establishing shot first, people
  and emotion in the middle, the best shot last. If there are no files, ask for them.
- **Song**: a local file, or download one:
  ```bash
  contentkit fetch --list "song words"                         # already downloaded?
  contentkit fetch --search "<song> <artist> remix" --audio    # top YouTube result, mp3
  contentkit fetch URL --audio                                 # exact video
  ```
  Tell the user the title that was downloaded so they can say if it's the wrong version.
  Check the beat: `contentkit beats song.mp3` (BPM, first beat, hook start).
- **Clips from social sites** (Instagram, Facebook, TikTok, X, Reddit, YouTube):
  ```bash
  contentkit fetch "<post url>" --out content/<job>/media                   # public posts
  contentkit fetch "<post url>" --browser chrome --out content/<job>/media  # needs login (IG/FB)
  contentkit fetch "<url>" --section 12-20 --out content/<job>/media        # just the part you need
  ```
  If it says the site wants a login, retry with `--browser` (chrome, brave, firefox, edge:
  whichever the user is logged in with).
- **Words**: names, dates, places, prices, ratings. Use their real wording.
- **Brand**: `brand.yaml` in the project if present; otherwise an inline brand in the
  recipe (`brand: {preset: fresh, colors: {accent: "#e8572a"}, look: warm}`).

## Plan a shoot (before there's footage)

```bash
contentkit shotlist hotel        # birthday food product real-estate wedding event talking-head
contentkit hooks                 # hook formulas by category (pov, curiosity, local ...) + rules
```
Hand the user the shot list as a checklist; write 3 hook lines for their idea from the formulas.

## Copy an edit from a reference video ("make it like this one")

```bash
contentkit reference analyze "<url or file>" -o content/<job>/ref     # shots, timing, text, beat, hook
contentkit reference recipe content/<job>/ref/analysis.json --media content/<job>/media -o content/<job>/recipe.yaml
```
Open `ref/shots.jpg` and `ref/ANALYSIS.md` and write the beat sheet (setup, turn, payoff,
why it works). The recipe keeps the reference's shot count, shot lengths (or beats),
text positions and music sync, filled with the user's media in order. Then:
- reorder media so each shot matches the reference shot's framing and role;
- replace every `<rewrite: ...>` with the user's own words (rendering refuses placeholders);
- `--use-audio` keeps the reference's sound: fine for private use, but for posting use the
  user's own or in-app audio (platforms demote reused audio and footage).
To study many openings: `contentkit hooks collect URL URL ... --seconds 3`.

## 2. Start from a template

```bash
contentkit template list
contentkit template new birthday-remix content/<job>      # or hotel-remix, meme-edit, commentary
```
This writes `content/<job>/recipe.yaml` and a `media/` folder. Edit the recipe: fill every
`<...>`, point `image:` / `video:` at the real files, delete unused scenes, add scenes
for extra shots. Recipe paths are relative to the recipe file.

Music-driven edits (no voiceover): `music: {start: hook, sync: beat, beats_per_cut: 2,
pulse: true}`, `transition: cut`, `captions: false`. Give the big moments `beats: 4`
(reveal, cake, group shot) and fast moments `beats: 1`.

With a voiceover or talking clip: music `volume: 0.25-0.3`, `duck: true`, `pulse: 0.02`,
`captions: {style: pop}` (or clean / boxed / serif).

The full recipe reference is in the contentkit README (`Video` section).

## Meme and commentary edits (any `video:` scene; `image:` takes the overlays too)

| Edit | Recipe | Use it for |
|---|---|---|
| POV / tweet header | `header: "POV: ..."` | the setup line of a meme |
| Classic meme text | `meme: {top: "...", bottom: "..."}` | image macros, reactions |
| Timed text | `texts: [{at, until, text, style: meme/label/plain, position}]` | punchlines, notes |
| Red circle / arrow / box | `callouts: [{at, until, shape, rect: [x, y, w, h], label}]` | "look at this" |
| Dramatic zoom | `zoom_to: {at, focus: [x, y], scale: 2.2, hold: 1}` | reactions (auto vine-boom) |
| Freeze frame | `freeze: {at, hold}` | "wait for it" (auto record-scratch) |
| Slow-mo / speed-up / rewind | `speed: 0.5`, `speed: 2`, `reverse: true` | fails, replays |
| Split screen | `split: {video, start, labels: [A, B]}` | before/after, this vs that |
| Reaction cam | `pip: {video, start, corner: tr, size: 0.32}` | commentary, reactions |
| Source credit | `source: "via @handle"` | clipped footage |

`rect` and `focus` are fractions of the frame (0-1): read them off the proof sheet.
Comedy sounds: `vine-boom record-scratch airhorn dramatic boing slide-up slide-down
sad-trombone cha-ching` (+ `contentkit sfx add file.mp3` for your own). Set `sfx: null`
on a zoom/freeze to silence its automatic sound.

Comedy timing: setup 1-2 s, then a beat (freeze, silence or zoom), then the payoff, out
within a second. Cut so the payoff is the last thing; don't explain the joke on screen.

## Footage fixes and meme placement (video scenes)

| Need | Recipe |
|---|---|
| Shaky handheld | `stabilize: true` (or `strong`) |
| Grainy low light | `denoise: light / medium / strong` |
| Horizontal clip in a vertical reel, keep the face in frame | `reframe: auto` |
| Green-screen meme clip over the footage | `overlay: [{video: meme.mp4, at, until, key: green, position: center, scale: 0.7}]` |
| Sticker / reaction image | `stickers: [{image, at, until, position: br, scale: 0.35, cutout: true}]` (`cutout` needs rembg) |
| Music stops for the punchline | `mute_music: true` on the punchline scene |
| One scene in black and white | `look: noir` on that scene |

## Meme and funny posters

| Layout | Fields | Use |
|---|---|---|
| `meme` | image, top, bottom | classic image macro |
| `versus` | images: [a, b], labels, title | expectation vs reality, before/after |
| `post` | text, name, handle, avatar, image, meta | text post card under the user's own name |
| `comic` | panels: [{image, caption, speech}], title | 2-4 panel strip |

Examples: `examples/memes/*.yaml`. Never put a real platform's logo or another person's
name/handle on a `post` card.

## 3. Render a preview, look at it, fix it

```bash
contentkit video content/<job>/recipe.yaml -o content/<job>/out --only reel
contentkit proof content/<job>/out/<name>-reel.mp4
```
**Open the proof JPG and look at it** before calling anything done. Check: faces not
cropped (fix with `focus: [x, y]`, 0-1), text readable, no text touching edges, the
story order, the end card.

Then critique it like an editor:
```bash
contentkit analyze content/<job>/out/<name>-reel.mp4 --kind meme   # or remix, commentary, brand
```
It scores hook speed, pacing, longest shot, dead air, loudness, black/frozen frames,
hook-frame text and face, first-second motion, loop, and soft/badly exposed shots.
Fix every `FIX` (or say why it's intentional, e.g. a freeze-frame gag), consider each
`IMPROVE`, re-render, re-run. Aim for 80+. Tell the user the score and what you changed.
Then render every format (drop `--only`). Report the files in `out/`, the proof sheet
path and the analysis.

## 4. Posters, carousels, thumbnails

```bash
contentkit layouts                                     # editorial swiss split quote stat event offer
contentkit poster recipe.yaml -o out/poster.jpg [--format reel|square|portrait|landscape]
contentkit print  recipe.yaml --size a3 -o out/poster  # print PDF + CMYK TIFF + proof
```
A carousel is a recipe with `slides:` (each slide picks a `layout`). Always look at the result.

## 5. Other tools

| Need | Command |
|---|---|
| Remove pauses from a talking clip (+ punch-in) | `contentkit cut take.mp4 --punch 1.1` |
| Clean a voice recording | `contentkit clean take.wav --master` |
| Captions on any video | `contentkit captions video.mp4 --style pop --srt` |
| Check platform UI overlap | `contentkit safezone frame.jpg` |
| Preview colour looks | `contentkit looks --preview photo.jpg` |
| Sound effects | `contentkit sfx list` (whoosh, pop, boom, sparkle, riser ...) |

## Growing an audience (what to tell the user when they'll post)

- Platforms rank by watch time, completion, replays, and shares/sends; they demote "see less".
- **Originality:** accounts that keep reposting other people's videos or audio get reduced
  reach on everything (Meta, 2025). Downloads are for study and private edits; for posting,
  rebuild the idea with the user's own footage and words, and use in-app or own audio.
- **No engagement bait** ("tag a friend", "comment YES", "like if"): demoted. Ask a genuine
  question in the caption instead.
- Under 30 s, payoff before the end, no outro card; a loop to frame 1 earns replays.
- Post consistently in one niche; caption = one line of context + a real question + 3-5
  specific hashtags (place, niche, format), not 30 generic ones.

## Design rules (keep the output from looking generated)

- Real photos and clips over flat colour cards; at most one card at the end.
- One accent colour, used for one emphasised word (`*word*`) and kickers.
- Short titles: under 6 words. Put names and numbers in the user's own words.
- Don't stack effects: either pulse or fancy transitions, not both everywhere.
- Never leave `<placeholders>` in a render. Never invent facts (prices, ratings, dates).
