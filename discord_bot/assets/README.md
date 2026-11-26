# War map art

Used by the war map image (`clash_war_image.py`). Anything missing falls back to the TH emojis /
drawn shapes, so the board never breaks. Restart the bot after changing files.

These are Supercell's game assets, used under Supercell's Fan Content Policy
(https://supercell.com/en/fan-content-policy/). The policy's disclaimer is left off the image because
this bot only runs on a private server; add it back if the images are ever shared publicly.
They're used as-is (only scaled), as the policy doesn't allow modifying them.
Copied from https://github.com/ClashKingInc/ClashKingAssets (game asset folders only).

| Path | What | Source in ClashKingAssets |
| --- | --- | --- |
| `townhalls/<level>.webp` | Town hall art, levels 1–19 | `assets/buildings/home-village/town_hall/level_<n>.webp` |
| `stars/full.png`, `stars/empty.png` | War stars | `assets/bot/icons/war_star.png`, `no_star.png` |
| `icons/attack.png` | Attack left | https://www.ashwingur.com/assets/coc/sword.png |
| `icons/missed.png` | Missed attack | `assets/bot/icons/broken_sword.png` |
| `fonts/SCmagic.ttf` | Supercell Magic, the in-game font (Latin/Cyrillic/Greek; other scripts fall back to Noto) | `assets/fonts/SCmagic.ttf` |
| `island.jpg` | Island surface for both sides (war map parchment), cover-cropped to each island | Supplied by you |
| `background.webp` | Map background (cover-cropped). ClashKing's own war artwork, not a Supercell file — it comes under the repo's GPL-3.0 licence | `assets/clashking/headers/war/war-wood-header.webp` |

When a new Town Hall level comes out, add `townhalls/<level>.webp` (and the emoji id in
`clash_common.py`); until then it shows a "TH<n>" placeholder.
