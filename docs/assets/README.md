# Website assets

The compass is the project icon (`../logo.svg`). The social preview is rendered from
`social-preview.html` at 1280 × 640. `social.jpg` is the sharing image; `../og.png`
remains available for existing links. PNG icons are exports of the same SVG.

The interactive chart uses the recorded DuckDB example in the main README and
`../demo.sh`, not a live database connection. Its data is in the `rehearsal-data`
JSON element in `../index.html`. The graph uses a common linear scale from zero to
400 million output rows, including the forecast interval. Original samples, the
forecast and actual full run stay distinct. No queries are run by the website.

`site.js` provides the recorded-example selector, installation tabs and clipboard
buttons. The page remains readable without JavaScript. `atlas.css` supplies the
shared presentation without changing the documented SQL or budget policies.
