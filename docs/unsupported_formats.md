# Formats the engine can't decode

ffmpeg can't decode camera raw formats: **Blackmagic RAW (.braw), RED (.r3d), ARRIRAW (.ari/.arx),
Canon Cinema RAW Light (.crm), Nikon N-RAW (.nev)**. The engine stops with a message if you pick one.

## Workaround: export from DaVinci Resolve (free)

1. Import the clip into a Resolve project.
2. In the **Camera RAW** settings, decode to the camera's native gamut and log. For example:
   - BRAW: Blackmagic Wide Gamut / Film Gen 5
   - RED: REDWideGamutRGB / Log3G10
   - ARRI: AWG3 / LogC3, or AWG4 / LogC4
3. On the Deliver page, choose **EXR (half float, ZIP or PIZ)**, or **ProRes 4444/422 HQ** if disk space
   matters.
4. Pick the colour space in the panel:
   - **Easiest:** also apply a Color Space Transform to *Rec.709 / Linear* in Resolve, export EXR, and
     choose **Linear Rec.709** in the panel.
   - **Or** export in camera log and use **Other (OCIO)** with the camera's OCIO space name (needs
     `pip install opencolorio` in the venv).

Don't export these as 8-bit H.264. The key loses edge detail and log footage bands.
