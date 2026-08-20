const puppeteer = require('puppeteer-core');
const path = require('path');

// "Navigating frame was detached" hits intermittently when a previous headless
// Chrome is still shutting down — observed once mid-build. The failure is
// transient and the build is idempotent, so retry rather than fail a 50-page
// render on a race.
async function withRetry(fn, attempts = 3) {
  for (let i = 1; i <= attempts; i++) {
    try { return await fn(); }
    catch (e) {
      if (i === attempts) throw e;
      console.error(`  retry ${i}/${attempts - 1} after: ${e.message}`);
      await new Promise(r => setTimeout(r, 1500 * i));
    }
  }
}

const render = async () => {
  const [src, out, startPage] = process.argv.slice(2);
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new', args: ['--no-sandbox','--allow-file-access-from-files'],
  });
  const page = await browser.newPage();
  // HIGH-DPI VIEWPORT, SET BEFORE LOAD.
  //
  // The diagrams ship as PNG screenshots (see rasteriseDiagrams below). At the
  // default deviceScaleFactor of 1 the PNG has exactly as many pixels as the
  // diagram has CSS pixels, so the print step has nothing extra to work with and
  // every label comes out soft — reported by the owner on 2026-08-20.
  //
  // deviceScaleFactor 4 captures 4x the pixels. The image is then placed back at
  // its CSS width, so a diagram laid out at 960px screen width and printed into
  // a 174mm text column (~658 CSS px) carries 3840 real pixels across that
  // column — roughly 560 DPI, well past what any printer resolves.
  //
  // The viewport WIDTH also matters: mermaid lays flowcharts out against the
  // container, so a narrow viewport wraps labels and stacks nodes. 960px is
  // close to the printed column's proportions, which keeps the on-page layout
  // the same shape as the captured one.
  await page.setViewport({width: 960, height: 1400, deviceScaleFactor: 4});
  await page.goto('file://' + path.resolve(src), {waitUntil: 'networkidle0', timeout: 120000});
  // RASTERISE THE DIAGRAMS BEFORE PRINTING.
  //
  // Mermaid renders to inline SVG. A PDF containing vector SVG looks perfect in
  // a PDF reader and FALLS APART when imported into Google Docs: the shapes are
  // stripped and only the text survives, scattered across the page. Reported by
  // the owner with a screenshot on 2026-08-18.
  //
  // Screenshotting each diagram element to PNG and swapping the SVG for an <img>
  // makes the diagram a single flat image, which survives conversion into Docs,
  // Word, and anything else that cannot parse vector markup.
  const rasteriseDiagrams = async () => {
    // UNCLAMP BEFORE CAPTURE. The stylesheet caps a diagram at the printable
    // height with `max-height: 195mm`, but an SVG with a viewBox does not crop
    // to that — it LETTERBOXES, keeping a full-width box and shrinking the
    // drawing inside it. The screenshot then spends its pixels on white bars.
    // Capture at natural size instead; the fit maths below does the scaling, and
    // does it on the real aspect ratio.
    await page.addStyleTag({content:
      '.mermaid svg { max-width: none !important; max-height: none !important;' +
      ' width: auto !important; height: auto !important; }'});
    await new Promise(r => setTimeout(r, 400));

    // TAG FIRST, THEN REPLACE. The first version of this iterated a snapshot of
    // .mermaid elements but re-selected by INDEX inside the loop. Every
    // replacement shrinks the live NodeList, so the indices drift and the last
    // diagram is never converted — while the log still claimed all three were.
    // Two of three shipped as images and one stayed vector, which is the exact
    // bug this function exists to fix.
    await page.evaluate(() =>
      document.querySelectorAll('.mermaid').forEach((el, i) =>
        el.setAttribute('data-diagram', String(i))));

    const ids = await page.evaluate(() =>
      [...document.querySelectorAll('[data-diagram]')].map(e => e.getAttribute('data-diagram')));

    let done = 0;
    for (const id of ids) {
      // Screenshot the SVG, NOT its <pre> wrapper. The wrapper is a block
      // element and always spans the full container width; a tall diagram that
      // the `max-height: 195mm` rule has shrunk sits in the middle of it
      // surrounded by white. Capturing the wrapper spent half the pixel budget
      // on that margin and halved the effective resolution of exactly the
      // diagrams that needed it most.
      const el = (await page.$(`[data-diagram="${id}"] svg`))
              || (await page.$(`[data-diagram="${id}"]`));
      if (!el) continue;
      const box = await el.boundingBox();
      if (!box || box.width < 5 || box.height < 5) continue;
      const b64 = (await el.screenshot({type: 'png', omitBackground: false})).toString('base64');
      // FIT THE IMAGE TO THE PRINTABLE BOX, IN BOTH DIRECTIONS.
      //
      // A4 minus 18mm side and 20mm top/bottom margins is 174 x 257mm, and a
      // diagram is given at most 195mm of height so a caption and some text can
      // share the page. At 96 CSS px per inch that is 658 x 737 px.
      //
      // The CSS rule `.mermaid svg { max-height: 195mm }` used to enforce this,
      // but it stops applying the moment the SVG becomes an <img> — so without
      // this a tall diagram would print past the page edge and be silently
      // guillotined by the paginator. Scale on the binding dimension, never up.
      const FIT_W = 658, FIT_H = 737;
      const scale = Math.min(FIT_W / box.width, FIT_H / box.height, 1);
      const drawWidth = Math.round(box.width * scale);
      await page.evaluate((sel, data, cssWidth) => {
        const node = document.querySelector(`[data-diagram="${sel}"]`);
        if (!node) return;
        const img = document.createElement('img');
        img.src = 'data:image/png;base64,' + data;
        // Pin the image back to the width the diagram actually occupied. Without
        // this an <img> defaults to its NATURAL size, which at deviceScaleFactor
        // 4 is four times too wide; max-width:100% would then rescale every
        // diagram to the full column regardless of how small it really is.
        img.style.width = cssWidth + 'px';
        img.style.maxWidth = '100%';
        img.style.height = 'auto';
        img.style.display = 'block';
        img.style.margin = '0 auto';
        node.replaceWith(img);
      }, id, b64, drawWidth);
      console.error(`    diagram ${id}: ${Math.round(box.width)}x${Math.round(box.height)} css` +
        ` -> ${drawWidth}px wide (${(box.width * 4 / drawWidth).toFixed(1)}x pixel density)`);
      done++;
    }

    // Verify rather than assert. A log that says "3" while 2 happened is worse
    // than no log.
    const left = await page.evaluate(() => document.querySelectorAll('.mermaid, svg').length);
    console.error(`  rasterised ${done}/${ids.length} diagram(s); ${left} vector element(s) left`);
    if (left > 0) throw new Error(`rasterisation incomplete: ${left} vector element(s) survived`);
  };

  // wait for every mermaid block to become an <svg>
  await page.waitForFunction(
    () => document.querySelectorAll('pre.mermaid, .mermaid').length === 0 ||
          document.querySelectorAll('.mermaid svg').length ===
          document.querySelectorAll('.mermaid').length,
    {timeout: 120000});
  // Mermaid animates in; give layout a beat before screenshotting, or the
  // captured PNG can be a half-drawn diagram.
  await new Promise(r => setTimeout(r, 2500));
  await rasteriseDiagrams();

  const off = parseInt(startPage || '1', 10) - 1;
  await page.pdf({
    path: out, format: 'A4', printBackground: true,
    margin: {top:'20mm', bottom:'20mm', left:'18mm', right:'18mm'},
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate:
      `<div style="width:100%;font-family:Georgia,serif;font-size:9px;color:#555;
        padding:0 18mm;display:flex;justify-content:space-between;">
        <span></span><span class="pageNumber"></span></div>`,
  });
  await browser.close();
  console.log('OK', out);
};

withRetry(render).catch(e => { console.error('FAIL', e.message); process.exit(1); });
