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
  // wait for every mermaid block to become an <svg>
  await page.waitForFunction(
    () => document.querySelectorAll('pre.mermaid, .mermaid').length === 0 ||
          document.querySelectorAll('.mermaid svg').length ===
          document.querySelectorAll('.mermaid').length,
    {timeout: 120000});
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
