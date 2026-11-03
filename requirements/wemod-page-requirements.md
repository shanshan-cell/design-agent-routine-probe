# WeMod page requirements (probe runs, Test D onward)

Three requirements every WeMod page a probe run designs must meet, on both page boards. Test C and the 29 Oct manual
exploration both missed all three. They sit on top of the wemod-page-designer skill and WeMod Web V0; where V0 is
silent or open, this file decides for probe runs until the design owner moves the rule into V0 or the skill.

`tools/check_requirements.py` checks them on the board files, and the guard runs the same check on every publish of
`project/Page-1440.dc.html` or `project/Page-390.dc.html`. A failing board is never published.

## Scope · one game or many

R1–R3 apply to every WeMod page a probe run designs. Where they name RDR2 they describe the RDR2 brief; for a page
about many games (game discovery, all games) read them as follows, without relaxing anything:

- R2: the phone action is all games (`https://www.wemod.com/cheats`) or a game page the brief names.
- R3: every game, route, mod count and store shown comes from the brief or V0's `Catalog Thumbnails` and capture
  fixtures. The denylist applies in full (its stores, sample screenshots and RDR2 Page Media stay blocked), and a
  store the brief doesn't verify is never named or shown.

## R1 · "WeMod by Wand" brand line

- The words **WeMod by Wand** appear, exactly so, as visible text on both boards at least once. Put them in the brand
  chrome (beside or under the WeMod mark in the header, or in the footer's brand block), not in a heading or a CTA.
- Set them in WeMod type and colour (Inter, `text-secondary` or white, at least 12 px). The WeMod mark stays the only
  logo: no Wand wordmark, Wand token, Wand component or Wand visual. This keeps V0's rule 4 and D7 ("nothing from
  Wand") intact. Only the words are added.
- The rest of the page still speaks as WeMod: the product, the app and the download are "WeMod".
- Why this is a probe rule and not yet a V0 rule: V0 records brand architecture as open (`RebrandBanner`, GRO-2648,
  WAND-7912), and the brief requires the line. Report it as a decision for the design owner.

## R2 · A clear next step on the phone

A phone visitor cannot install WeMod, so the 390 board never offers a download (skill rule 7, V0 03 platform rules).
It ends with a next step that works on a phone:

- **The verified line:** "…or visit us on your PC to download the app" (`get_started_nonwindows.or_visit_pc`, 11).
  You may lead into it with your own short heading.
- **One real action under it** that works on a phone, at least 44 px: a link to the game page
  (`https://www.wemod.com/cheats/red-dead-redemption-2-trainers`) or to all games (`https://www.wemod.com/cheats`).
- **No download on the phone board:** no link to `wemod.com/download`, no "Free download" or "Download" button, no
  `data-app-download-button`. "Get Started" (the email dialog, R46) isn't built, so it isn't used either.
- The 1440 board is the Windows visitor and keeps the download path (`https://www.wemod.com/download`).
- Why: both previous phone boards linked to the Windows download, and Test C's phone closing had no action at all.

## R3 · No unverified game, store or mod imagery

On a page about one game or one mod, every image, icon and screenshot must be true of that game:

- **Stores:** only the stores verified for the game. RDR2: Steam, Rockstar Games, Epic Games. No GOG, Ubisoft,
  Origin, EA or Xbox marks.
- **Games and mods:** no screenshot, overlay or illustration that shows another game, a sample "Your Game", or mods
  and categories the game doesn't have (RDR2 has 11 mods in Player, Inventory, Weapons, Vehicles; V0 04 §3).
- **RDR2-specific media** stay out until approved (brief).
- `requirements/v0-asset-denylist.json` lists the V0 assets this rules out, by asset id and sha256. The guard
  blocks reading, copying or uploading them. The list is what we found, not a whitelist: any other image you use must
  pass the same test, and the reviewer checks it on the render.
- When a step or section has no truthful image, use type, the verified store icons, the mod-category icons of the
  game's own groups, or no image. Never a generic stand-in.
