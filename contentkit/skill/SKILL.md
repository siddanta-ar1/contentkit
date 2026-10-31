---
name: contentkit
description: Make finished videos, reels, posters, carousels and thumbnails locally with contentkit. Use whenever the user asks to make, edit or render a video, reel, short, TikTok, story, slideshow, birthday/wedding/party/event video, hotel/restaurant/product review, promo, remix-style or beat-synced edit, meme, funny or comedy edit, reaction, commentary, breakdown or analysis video, lyric or music video, poster, flyer, banner, carousel, thumbnail, or print file; when they want a song or clip downloaded (YouTube, Instagram, Facebook, TikTok, X, Reddit) and used; when they want a video critiqued or improved; or when they mention contentkit.
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
It scores hook speed, pacing, longest shot, dead air, loudness, black/frozen frames.
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

## Design rules (keep the output from looking generated)

- Real photos and clips over flat colour cards; at most one card at the end.
- One accent colour, used for one emphasised word (`*word*`) and kickers.
- Short titles: under 6 words. Put names and numbers in the user's own words.
- Don't stack effects: either pulse or fancy transitions, not both everywhere.
- Never leave `<placeholders>` in a render. Never invent facts (prices, ratings, dates).
