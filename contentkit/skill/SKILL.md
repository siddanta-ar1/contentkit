---
name: contentkit
description: Make finished videos, reels, posters, carousels and thumbnails locally with contentkit. Use whenever the user asks to make, edit or render a video, reel, short, TikTok, story, slideshow, birthday/wedding/party/event video, hotel/restaurant/product review, promo, remix-style or beat-synced edit, lyric or music video, poster, flyer, banner, carousel, thumbnail, or print file; when they want a song (Nepali lok, remix, any track) downloaded and used as the soundtrack; or when they mention contentkit.
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
- **Words**: names, dates, places, prices, ratings. Use their real wording.
- **Brand**: `brand.yaml` in the project if present; otherwise an inline brand in the
  recipe (`brand: {preset: fresh, colors: {accent: "#e8572a"}, look: warm}`).

## 2. Start from a template

```bash
contentkit template list
contentkit template new birthday-remix content/<job>      # or hotel-remix
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

## 3. Render a preview, look at it, fix it

```bash
contentkit video content/<job>/recipe.yaml -o content/<job>/out --only reel
contentkit proof content/<job>/out/<name>-reel.mp4
```
**Open the proof JPG and look at it** before calling anything done. Check: faces not
cropped (fix with `focus: [x, y]`, 0-1), text readable, no text touching edges, the
story order, the end card. Fix the recipe and re-render. Then render every format
(drop `--only`). Report the files in `out/` plus the proof sheet path.

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
