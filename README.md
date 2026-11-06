# macros
Macros/scripts for Adobe, Excel, Solidwords, etc etc useful in technical writing contexts

## LineDensityCleanUp

File: [`Illustrator/LineDensityCleanUp_v5.jsx`](Illustrator/LineDensityCleanUp_v5.jsx)

LineDensityCleanup is an Adobe Illustrator script that removes identical and near-identical paths in CAD-derived technical drawings. Its purpose is to automatically reduce the visual noise and weight of excessive pathing sometimes inherent in the export of complex CAD drawings to 2D formats such as DXF. The script should, however, work on any .AI file with very dense paths. **PLEASE NOTE** to function, you must label the target layer "origin", as the script targets and operates only on the layer named 'origin'. It is set up this way with the intention of being the first step in creating an illustration after import.

## LineDensityCleanUp for DXF

Files: [`DXF/LineDensityCleanUp_dxf.py`](DXF/LineDensityCleanUp_dxf.py), [`DXF/LineDensityCleanUp_dxf.bat`](DXF/LineDensityCleanUp_dxf.bat)

A Python version of LineDensityCleanUp that cleans the DXF *before* it is imported into Illustrator. It uses the same detection logic and the same settings as the Illustrator script (exact duplicates, near-parallel lines, and leftover fragments), so Illustrator only receives the lines you keep. Tested to give identical results to the Illustrator script's logic on the same geometry.

The original DXF is not changed. For each file, the script writes:

- `<name>_clean.dxf`: the drawing with the removed lines taken out. Import this into Illustrator.
- `<name>_review.dxf`: the full drawing, with removed lines moved to colored layers (`LDC_Duplicates` in red, `LDC_Near-parallel` in blue, `LDC_Fragments` in magenta) so you can check what was taken out.

### Setup (once)

1. Install Python 3 from [python.org](https://www.python.org/downloads/). On Windows, check **Add python.exe to PATH** during installation.
2. Open a command prompt and run: `pip install ezdxf`

### Use

**Drag and drop (Windows):** drag one or more `.dxf` files onto `LineDensityCleanUp_dxf.bat`. Type the final printed width of the figure when asked (for example `4in` or `100mm`).

**Command line:**

```
python LineDensityCleanUp_dxf.py drawing.dxf --width 4in
python LineDensityCleanUp_dxf.py *.dxf --width 6.5in --layers Visible
```

| Option | Meaning |
|---|---|
| `--width` | Final printed width of the figure: `4in`, `100mm`, `288pt`. A bare number is read as inches. |
| `--scale` | Instead of `--width`: points per drawing unit at final size. |
| `--layers` | Clean only these DXF layers (comma-separated). Default: all layers. |
| `--no-explode` | Leave block references alone. Their lines are then not checked. |
| `--out-dir` | Write the output files to this folder instead of next to each input. |

### Notes

- **Why the width matters.** The tolerances are in points at the figure's final printed size, as in the Illustrator script (for example, lines within 0.4 pt of each other count as near-parallel). A DXF is drawn at full scale, so the script needs the final width to convert those tolerances. If you later import the clean DXF at a different size, the cleanup will have been tuned for the wrong size.
- **What is checked:** lines, arcs, circles, ellipses, splines, and polylines. Text, dimensions, hatches, and other entities pass through unchanged.
- **Block references** are exploded into individual lines so each one can be checked. Use `--no-explode` to keep blocks intact.
- **Settings** are at the top of `LineDensityCleanUp_dxf.py` and match the Illustrator script's settings.
- **Speed:** about 7 seconds for a 6,000-line test drawing and about 90 seconds for 30,000 lines on a 2-core machine. Time grows with total line length at final size.
