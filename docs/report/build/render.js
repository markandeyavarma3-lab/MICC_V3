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
      const el = await page.$(`[data-diagram="${id}"]`);
      if (!el) continue;
      const box = await el.boundingBox();
      if (!box || box.width < 5 || box.height < 5) continue;
      const b64 = (await el.screenshot({type: 'png', omitBackground: false})).toString('base64');
      await page.evaluate((sel, data) => {
        const node = document.querySelector(`[data-diagram="${sel}"]`);
        if (!node) return;
        const img = document.createElement('img');
        img.src = 'data:image/png;base64,' + data;
        img.style.maxWidth = '100%';
        img.style.height = 'auto';
        img.style.display = 'block';
        img.style.margin = '0 auto';
        node.replaceWith(img);
      }, id, b64);
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
