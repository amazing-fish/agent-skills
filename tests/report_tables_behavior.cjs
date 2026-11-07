// Pure mocked-DOM behavior checks, not browser layout or accessibility acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const js = fs.readFileSync(path.join(__dirname, '../skills/report-for-human/assets/report-tables.js'),'utf8');
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.style={width:'',minWidth:''};this.attrs={};this.events={};this.textContent='';this.colSpan=1;this.rowSpan=1;this.span=1;this.open=false;this.className='';}
  get classList(){return {contains:n=>this.className.split(' ').includes(n)}}
  appendChild(el){this.children.push(el);el.parentElement=this;el.parentNode=this;return el}
  insertBefore(el,before){this.children.splice(this.children.indexOf(before),0,el);el.parentElement=this;el.parentNode=this}
  setAttribute(k,v){this.attrs[k]=String(v)}
  hasAttribute(k){return k in this.attrs}
  addEventListener(k,f){(this.events[k] ||= []).push(f)}
  fire(k){(this.events[k]||[]).forEach(f=>f({target:this}))}
  querySelector(s){if(s==='table')return this.nested||null;throw Error(s)}
  getBoundingClientRect(){return {width:this.measured}}
}
function fixture(widths=[180,420,300]){
  let root=new Element('main'),wrap=root.appendChild(new Element('div'));wrap.className='rfh-table-wrap';
  let table=wrap.appendChild(new Element('table'));table.className='rfh-table';table.setAttribute('data-rfh-resizable','');
  let group=table.appendChild(new Element('colgroup'));
  widths.forEach((w,i)=>{let c=group.appendChild(new Element('col'));c.style.width=['20%','47%','33%'][i]||'10%'});
  let headers=widths.map((w,i)=>{let h=new Element('th');h.textContent=['名称','说明','限制'][i]||`字段${i}`;h.measured=w;return h});
  table.tHead={rows:[{cells:headers}]}; table.rows=[...table.tHead.rows,{cells:widths.map(()=>new Element('td'))}];
  return {root,wrap,table,group,headers};
}
function boot(pages,loading=false){
  const doc={readyState:loading?'loading':'complete',createElement:t=>new Element(t),querySelectorAll:()=>pages.map(x=>x.table),addEventListener(k,f){this[k]=f}};
  const win={events:{},addEventListener(k,f){(this.events[k] ||= []).push(f)},fire(k){(this.events[k]||[]).forEach(f=>f())}};
  const context={document:doc,window:win};vm.runInNewContext(js,context);
  if(loading)doc.DOMContentLoaded();
  return {doc,win,again(){vm.runInNewContext(js,context)}};
}
function controls(f){let panel=f.root.children[0],sliders=panel.children[2];return {panel,inputs:sliders.children.map(l=>l.children[2]),outputs:sliders.children.map(l=>l.children[1]),reset:panel.children[3]}}
function open(f){let c=controls(f);c.panel.open=true;c.panel.fire('toggle');return c}
let a=fixture(),b=fixture([240,480,360]),ctx=boot([a,b],true);
assert.equal(a.root.children.length,2); assert.equal(a.table.rows[0].cells[0],a.headers[0]);
assert.equal(a.group.children[0].style.width,'20%'); // no initial layout mutation
ctx.again();assert.equal(a.root.children.length,2); // idempotent
let c=open(a); assert.equal(c.inputs[0].type,'range');assert.equal(c.inputs[0].attrs['aria-label'],'名称 列宽');
assert.equal(c.inputs[0].value,180);assert.equal(c.outputs[0].value,'180 px');assert.equal(c.reset.disabled,true);
c.inputs[1].value='520';c.inputs[1].fire('input');
assert.deepEqual(a.group.children.map(x=>x.style.width),['180px','520px','300px']);assert.equal(a.table.style.width,'1000px');assert.equal(a.table.style.minWidth,'0px');
assert.equal(c.inputs[1].attrs['aria-valuetext'],'520 像素');assert.equal(c.reset.disabled,false);assert.equal(b.group.children[0].style.width,'20%');
c.inputs[1].value='99999';c.inputs[1].fire('input');assert.equal(c.inputs[1].value,960);assert.equal(a.table.style.width,'1440px');
c.inputs[0].value='-50';c.inputs[0].fire('input');assert.equal(c.inputs[0].value,120);
ctx.win.fire('resize');assert.equal(c.inputs[0].value,120); // preserve manual pixels
c.reset.fire('click');assert.deepEqual(a.group.children.map(x=>x.style.width),['20%','47%','33%']);assert.equal(a.table.style.width,'');assert.equal(a.table.style.minWidth,'');
a.headers[0].measured=240;ctx.win.fire('resize');assert.equal(c.inputs[0].value,240);assert.equal(c.reset.disabled,true);
let hidden=fixture([0,0,0]);boot([hidden]);let hc=open(hidden);assert.equal(hc.inputs[0].value,undefined);hidden.headers.forEach((h,i)=>h.measured=[100,1000,200][i]);hc.panel.fire('toggle');
assert.equal(hc.inputs[0].min,100);assert.equal(hc.inputs[1].max,1000);hc.inputs[0].value='150';hc.inputs[0].fire('input');assert.equal(hc.inputs[0].min,100);hc.inputs[0].value='100';hc.inputs[0].fire('input');assert.equal(hc.inputs[0].value,100);
for(const mutate of [
 f=>f.table.rows[1].cells[0].colSpan=2,
 f=>f.headers[0].rowSpan=2,
 f=>f.table.rows[1].cells.pop(),
 f=>f.table.tHead.rows.push({cells:f.headers}),
 f=>f.group.children.pop(),
 f=>f.group.children[0].span=2,
 f=>f.table.nested=new Element('table'),
 f=>f.headers[0].tagName='TD',
 f=>f.wrap.className='other',
 f=>f.table.tHead=null
]){let f=fixture();mutate(f);boot([f]);assert.equal(f.root.children.length,1);assert.equal(f.table.hasAttribute('data-rfh-table-ready'),false)}
for(const n of [1,9]){let f=fixture(Array(n).fill(200));boot([f]);assert.equal(f.root.children.length,1)}
console.log('Table mocked DOM regressions passed: sizing, isolation, reset, hidden tables, resize, bounds, unsupported shapes. Browser/assistive technology not covered.');
