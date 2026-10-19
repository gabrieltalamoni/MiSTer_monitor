# Console logo data

Source graphics: RetroPie Carbon theme by Rookervik, based on Simple by
Nils Bonenberger. https://github.com/RetroPie/es-theme-carbon

The SVG sources beside these JPEGs come from `<system>/art/system.svg` for snes, megadrive,
mastersystem, tg16, nes, n64 and psx. The upstream attribution/license text is
reproduced unchanged in UPSTREAM-LICENSE.txt. The upstream license identifies
these art assets as Attribution-NonCommercial-ShareAlike; it also states that
the used logos and trademarks belong to their respective owners. This notice
applies to these separate image data assets, not the GPL/AGPL program code.

Changes for this fork: rasterized with CairoSVG, cropped transparent margins,
resized proportionally, placed on a white 360x120 canvas and encoded as
baseline JPEG. Reproduce with `python3 tools/build_library_logos.py` (CairoSVG
and Pillow). The output JPEGs live in
`MiSTer/Scripts/.config/mister_monitor/library/logos/` and remain separate data
files; the firmware downloads and caches them without embedding the art.
