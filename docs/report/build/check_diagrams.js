const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless:'new'});
  const p = await b.newPage();
  await p.setViewport({width:1400, height:1000, deviceScaleFactor:2});
  await p.goto('file://' + process.argv[2], {waitUntil:'networkidle0'});
  await new Promise(r => setTimeout(r, 8000));
  const info = await p.evaluate(() => [...document.querySelectorAll('.mermaid')].map((e,i) => ({
      i, hasSvg: !!e.querySelector('svg'),
      w: e.querySelector('svg')?.getBoundingClientRect().width|0,
      h: e.querySelector('svg')?.getBoundingClientRect().height|0 })));
  console.log(JSON.stringify(info));
  const els = await p.$$('.mermaid');
  for (let i=0;i<els.length;i++) await els[i].screenshot({path:`/tmp/rdiag_${i}.png`});
  await b.close();
})();
