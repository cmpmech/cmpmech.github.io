# AGENTS.md

A static site: plain HTML plus `style.css`, with no build step except the publication renderer.

## Structure
- `index.html` is the landing page, with the research areas, software and hero video.
- `research/<area>.html` are the area pages. Each has *Key works* topics and a *Publications* list.
- `research/topics/<name>.html` are the topic sections. **Edit these, not the copies in the pages.**
  A `<!-- topic: name --> … <!-- /topic -->` marker in a page is replaced by the topic file.
- `style.css` holds the only styles. Its colour tokens are on `:root`, with a dark variant via
  `prefers-color-scheme`.
- `video.js` handles autoplaying videos: it respects reduced motion and switches to the
  `data-dark` / `data-dark-poster` source in dark mode.
- `assets/` holds the media. It is not tracked on `main` (see *Deployment*). `consistency/` holds the
  shared figure settings.

## Publications
- `publications/scholars.csv` lists the people to crawl. `publications/publications.csv` has one
  row per article. You maintain `category`, `summary` and `status`; the script fills the rest.
- `python3 publications/update_publications.py` crawls Google Scholar and Zenodo, then renders.
  With `--render-only`, it only re-inlines the topics and fills the `<!-- papers: … -->` lists.
  **Run it after every edit** to a topic or page.

## Figures and videos
- Colour maps:
  - Fields use ParaView's Rainbow Desaturated (`consistency/rainbow_desaturated.cmap`).
  - Densities and inversions use `hot` / `hot_r`. Choose case by case, so that the background
    end of the map suits the theme (e.g. white background in light mode, black in dark).
- Every figure comes in a light and a dark version. Render backgrounds, especially in 3D, match
  `--paper` in `style.css`: `#fbfbfc` (light) and `#0e1116` (dark).
- Asset names: `name-light.ext` / `name-dark.ext`, with posters `name-light-poster.jpg` /
  `name-dark-poster.jpg`.
  - Images: `<picture><source srcset="…-dark.png" media="(prefers-color-scheme: dark)"><img src="…-light.png"></picture>`.
  - Videos: `src="…-light.mp4" data-dark="…-dark.mp4"`, plus `poster` / `data-dark-poster`.
- Encode videos with `consistency/web_video.sh`: H.264, faststart, CRF ≈ 28. It writes a poster
  alongside the video.
- Figure markup:
  - Use `<figure class="figure">`, with `.figure-pair` (or `--3`) and `<h4>` panel labels.
  - The `<figcaption>` starts with "Topic: …".
  - It ends with `<span class="credit">powered by <a>neuralmech</a> · <a>mlhp</a> · <a>cuwave</a></span>`,
    listing the tools that actually produced the figure.
- Keep all `assets/` referenced: delete unused files and verify there are no broken paths.

## Deployment
- `main` holds the pages, and `assets/` is git-ignored. The media lives on the orphan `assets` branch
  as a single commit that is replaced on every publish, so git keeps no asset history.
- `.github/workflows/pages.yml` deploys `main` with the `assets` branch checked out into `assets/`, on
  every push to either branch.
- After changing anything in `assets/`, run `./publish_assets.sh`. It refuses to publish broken or
  unreferenced paths, does nothing if the assets are unchanged, and otherwise force-pushes the new
  `assets` commit.
- On a fresh clone, fetch the media with
  `git fetch origin assets && mkdir -p assets && git archive FETCH_HEAD | tar -x -C assets`.
- Never commit media to `main`.
