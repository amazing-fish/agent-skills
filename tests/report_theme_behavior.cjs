// Mocked DOM regression tests. These do not claim browser or visual acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const js = fs.readFileSync(path.join(__dirname, '../skills/report-for-human/assets/report-controls.js'), 'utf8');
function boot(saved=null,dark=false,blocked=false){
const root={dataset:{}}, select={disabled:true,value:"light",addEventListener:(e,f)=>select[e]=f};
const dummy=()=>({addEventListener(){},focus(){},select(){}});
const elements={"[data-rfh-theme-toggle]":select,"[data-rfh-copy-path]":dummy(),"[data-rfh-status]":dummy(),"[data-rfh-manual]":dummy(),"[data-rfh-manual-path]":dummy()};
const media={matches:dark,addEventListener:(e,f)=>media[e]=f};
let value=saved;const localStorage={getItem(){if(blocked)throw Error();return value},setItem(k,v){if(blocked)throw Error();value=v}};
new Function("document","window","localStorage","navigator",js)({documentElement:root,readyState:"complete",querySelector:s=>elements[s]}, {matchMedia:()=>media},localStorage,{});
return {root,select,media,get saved(){return value},pick(v){select.value=v;select.change()},system(v){media.matches=v;media.change()}};
}
for (const dark of [false, true]) {
  const page = boot(null, dark);
  assert.equal(page.root.dataset.reportTheme, 'light');
  assert.equal(page.select.value, 'light');
  for (const preference of ['system', 'light', 'dark']) {
    page.pick(preference);
    assert.equal(page.saved, preference);
    assert.equal(page.root.dataset.reportTheme, preference === 'system' ? (dark ? 'dark' : 'light') : preference);
    const refreshed = boot(page.saved, !dark);
    assert.equal(refreshed.select.value, preference);
    assert.equal(refreshed.root.dataset.reportTheme, preference === 'system' ? (!dark ? 'dark' : 'light') : preference);
  }
}
const page = boot('system', false);
page.system(true);
assert.equal(page.root.dataset.reportTheme, 'dark');
page.pick('light');
page.system(false);
page.system(true);
assert.equal(page.root.dataset.reportTheme, 'light');
page.pick('dark');
page.system(false);
assert.equal(page.root.dataset.reportTheme, 'dark');
assert.equal(boot('invalid', true).root.dataset.reportTheme, 'light');
const blocked = boot(null, true, true);
blocked.pick('system');
assert.equal(blocked.root.dataset.reportTheme, 'dark');
blocked.pick('light');
assert.equal(blocked.root.dataset.reportTheme, 'light');
console.log('34 mocked DOM theme assertions passed; visual acceptance not covered.');
