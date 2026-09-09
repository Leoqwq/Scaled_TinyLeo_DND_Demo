const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.install();
    await page.clock.pauseAt(new Date(Date.now() + 1000));
    await page.goto(pathToFileURL(process.argv[2]).href);
    assert.equal(await page.locator('#epoch').getAttribute('max'), '300');
    assert.equal(await page.locator('#speed').inputValue(), '1000');
    const data = await page.locator('#data').textContent().then(JSON.parse);
    assert.equal(data.modes.shortest.length, 301);
    for (let i = 0; i <= 300; i++) {
      assert.equal(data.modes.shortest[i].telemetry.simulation_time_s, i);
      assert.equal(Object.keys(data.modes.shortest[i].nodes).length, 102);
      await page.locator('#epoch').evaluate((e, i) => {e.value = i; e.dispatchEvent(new Event('input'));}, i);
      assert.match(await page.locator('#epochLabel').textContent(), new RegExp(`Frame ${i+1} / 301`));
    }
    assert.notDeepEqual(data.modes.shortest[0].nodes.SH1SAT1, data.modes.shortest[300].nodes.SH1SAT1);
    await page.locator('#play').click();
    assert.equal(await page.locator('#epoch').inputValue(), '0');
    await page.clock.runFor(999);
    assert.equal(await page.locator('#epoch').inputValue(), '0');
    await page.clock.runFor(1);
    assert.equal(await page.locator('#epoch').inputValue(), '1');
    await page.locator('#play').click();
    await page.clock.runFor(2000);
    assert.equal(await page.locator('#epoch').inputValue(), '1');
    await page.locator('#epoch').evaluate(e => {e.value = 299; e.dispatchEvent(new Event('input'));});
    await page.locator('#play').click();
    await page.clock.runFor(2000);
    assert.equal(await page.locator('#epoch').inputValue(), '300');
    assert.match(await page.locator('#play').textContent(), /Play/);
    assert.doesNotMatch(await page.locator('main').innerText(), /Failure injection|12 epochs|[\u4e00-\u9fff]/);
    assert.deepEqual(errors, []);
    await page.screenshot({path: '/tmp/tinyleo-seconds-replay.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    console.log('PASS: 301 frames, node data, 1-second clock, pause, seek, end, English UI, mobile layout.');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
