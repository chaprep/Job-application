# Document rendering templates

`resume-template.tex` preserves the A4 Inter résumé layout. The backend supplies the font directory discovered by `kpsewhich`; the `Path=./` value is a portable placeholder. `resume-template.pdf` is a synthetic candidate example used by extraction, hyperlink, and layout tests.

`cover-letter-template.tex` provides the independent US Letter Roboto layout. Synthetic approved letter content and its matching reference PDF live in `tests/fixtures/cover-letter-approved.*`.

The résumé uses 5 mm margins, 9.1 pt body text, and blue links. The cover letter uses a sidebar and main column with teal accents. Rendering checks page size, overflow, extracted text, glyphs, and link destinations. No candidate data is embedded in the cover-letter template; runtime values come from the reviewed workspace.

Reference images were generated with the native TeX/Poppler toolchain. Exact raster equality can vary with toolchain versions. Historical personal reference scripts are local-only and excluded from the repository and image.
