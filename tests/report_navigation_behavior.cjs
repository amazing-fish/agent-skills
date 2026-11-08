// Executable mocked-DOM regression tests, not native-browser or visual acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const navigation = fs.readFileSync(path.join(__dirname, '../skills/report-for-human/assets/report-navigation.js'), 'utf8');
const theme = fs.readFileSync(path.join(__dirname, '../skills/report-for-human/assets/report-controls.js'), 'utf8');
let focused;
class Element {
  constructor(tag, attrs={}) { this.tagName=tag.toUpperCase(); this.attrs={...attrs}; this.children=[]; this.dataset={}; this.events={}; this.hidden=false; this.isConnected=true; this.textContent=''; }
  get id(){ return this.attrs.id; }
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  hasAttribute(k){return k in this.attrs;}
  removeAttribute(k){delete this.attrs[k]; if(k==='src')delete this.src;}
  append(...items){items.forEach(item=>{item.parentElement=this;this.children.push(item);});}
  addEventListener(k,f){(this.events[k]??=[]).push(f);}
  emit(k,extra={}){const e={target:this,button:0,prevented:false,preventDefault(){this.prevented=true;},...extra};(this.events[k]||[]).forEach(f=>f(e));return e;}
  focus(){focused=this;}
  querySelector(q){return this.children.find(x=>q==='img'?x.tagName==='IMG':q==='figcaption'?x.tagName==='FIGCAPTION':false)||null;}
  closest(q){return this.parentElement?.tagName===q.toUpperCase()?this.parentElement:null;}
  getBoundingClientRect(){return {left:10,top:10,right:500,bottom:400};}
  showModal(){this.open=true;this.openCount=(this.openCount||0)+1;}
  close(){this.open=false;this.emit('close');}
}
function boot({dialogSupport=true, loading=false, malformed=false}={}) {
  focused=null;
  const body=new Element('main'), root=new Element('html'), ids={};
  const groups=['first','second'].map(prefix=>{
    const group=new Element('section'), list=new Element('div',{role:'tablist'});
    const tabs=[0,1,2].map(i=>new Element('button',{id:`${prefix}-tab-${i}`,'aria-controls':`${prefix}-panel-${i}`}));
    const panels=tabs.map((t,i)=>new Element('section',{id:`${prefix}-panel-${i}`,role:'tabpanel'}));
    tabs.forEach(t=>ids[t.id]=t);panels.forEach(p=>ids[p.id]=p);
    list.append(...tabs);group.append(list,...panels);body.append(group);return {group,list,tabs,panels};
  });
  if(malformed)groups[0].tabs[0].attrs['aria-controls']='second-panel-0';
  const links=['data:image/png;base64,AAAA','https://example.com/image.png','data:image/svg+xml;base64,AAAA'].map(source=>{
    const figure=new Element('figure'),link=new Element('a',{href:source}),img=new Element('img'),caption=new Element('figcaption');
    img.alt='完整的证据截图';caption.textContent='截图来源与说明';link.append(img);figure.append(link,caption);body.append(figure);return link;
  });
  const toggle=new Element('select');toggle.disabled=true;
  const controls={'[data-rfh-theme-toggle]':toggle};
  ['copy-path','status','manual','manual-path'].forEach(k=>controls[`[data-rfh-${k}]`]=new Element('div'));
  const ready=[];
  const document={body,documentElement:root,readyState:loading?'loading':'complete',querySelectorAll:q=>q==='.rfh-tabs'?groups.map(g=>g.group):q==='.rfh-image-link'?links:[],querySelector:q=>q==='.human-report'?body:controls[q]||null,getElementById:id=>ids[id],createElement:tag=>new Element(tag),addEventListener:(k,f)=>ready.push(f)};
  const media={matches:false,addEventListener:(k,f)=>media[k]=f};let saved=null;
  const localStorage={getItem:()=>saved,setItem:(k,v)=>saved=v};
  const run=()=>new Function('document','HTMLDialogElement',navigation)(document,dialogSupport?Element:undefined);
  new Function('document','window','localStorage','navigator',theme)(document,{matchMedia:()=>media},localStorage,{});
  run();ready.forEach(f=>f());
  return {groups,links,body,root,toggle,media,run,get dialog(){return body.children.find(x=>x.tagName==='DIALOG');}};
}
for(const loading of [false,true]){
  const page=boot({loading}), a=page.groups[0], b=page.groups[1];
  function selected(g,n){g.tabs.forEach((t,i)=>{assert.equal(t.getAttribute('role'),'tab');assert.equal(t.getAttribute('aria-selected'),String(i===n));assert.equal(t.tabIndex,i===n?0:-1);assert.equal(g.panels[i].hidden,i!==n);assert.equal(g.panels[i].getAttribute('aria-labelledby'),t.id);assert.equal(g.panels[i].tabIndex,0);});}
  selected(a,0);selected(b,0);
  for(const [index,key,want] of [[0,'ArrowLeft',2],[2,'ArrowRight',0],[0,'End',2],[2,'Home',0],[0,'ArrowRight',1]]){
    assert.equal(a.tabs[index].emit('keydown',{key}).prevented,true);selected(a,want);assert.equal(focused,a.tabs[want]);selected(b,0);
  }
  assert.equal(a.tabs[1].emit('keydown',{key:'Tab'}).prevented,false);
  b.tabs[2].emit('click');selected(b,2);selected(a,1);
  const dialog=page.dialog,link=page.links[0],toolbar=dialog.children[0],zoom=toolbar.children[1],close=toolbar.children[2],stage=dialog.children[1],image=stage.children[0],caption=dialog.children[2];
  assert.equal(dialog.tagName,'DIALOG');assert.equal(dialog.getAttribute('aria-label'),'放大图片');assert.equal(link.getAttribute('aria-haspopup'),'dialog');
  for(const other of page.links.slice(1))assert.equal(other.getAttribute('aria-haspopup'),null);
  for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{button:1}])assert.equal(link.emit('click',extra).prevented,false);
  assert.equal(dialog.open,undefined);
  assert.equal(link.emit('click').prevented,true);assert.equal(dialog.open,true);assert.equal(focused,close);assert.equal(image.src,link.getAttribute('href'));assert.equal(image.alt,'完整的证据截图');assert.equal(caption.textContent,'截图来源与说明');
  zoom.emit('click');assert.equal(dialog.dataset.original,'true');assert.equal(zoom.getAttribute('aria-pressed'),'true');
  zoom.emit('click');assert.equal(dialog.dataset.original,'false');
  for(const preference of ['dark','light','system']){page.toggle.value=preference;page.toggle.emit('change');assert.equal(page.root.dataset.reportTheme,preference==='system'?'light':preference);assert.equal(dialog.open,true);selected(a,1);}
  page.media.matches=true;page.media.change();assert.equal(page.root.dataset.reportTheme,'dark');
  close.emit('click');assert.equal(dialog.open,false);assert.equal(focused,link);assert.equal(image.src,undefined);
  for(let n=0;n<3;n++){link.emit('click');assert.equal(dialog.dataset.original,'false');assert.equal(zoom.getAttribute('aria-pressed'),'false');assert.equal(stage.scrollTop,0);assert.equal(stage.scrollLeft,0);dialog.emit('click',{clientX:100,clientY:100});assert.equal(dialog.open,true);dialog.emit('click',{clientX:0,clientY:0});assert.equal(dialog.open,false);assert.equal(focused,link);}
  // Simulate the native close event, not a claim that Escape/focus trapping was browser tested.
  link.emit('click');dialog.close();assert.equal(focused,link);
}
const fallback=boot({dialogSupport:false});assert.equal(fallback.dialog,undefined);assert.equal(fallback.links[0].emit('click').prevented,false);assert.equal(fallback.groups[0].group.hasAttribute('data-tabs-ready'),true);
const malformed=boot({malformed:true});assert.equal(malformed.groups[0].group.hasAttribute('data-tabs-ready'),false);assert.equal(malformed.groups[1].group.hasAttribute('data-tabs-ready'),true);malformed.groups[0].panels.forEach(p=>assert.equal(p.hidden,false));
const failed=boot();failed.dialog.showModal=()=>{throw new Error('Native modal unavailable');};assert.equal(failed.links[0].emit('click').prevented,false);
const detached=boot();detached.links[0].emit('click');const closeFocus=focused;detached.links[0].isConnected=false;detached.dialog.close();assert.equal(focused,closeFocus);
console.log('Mocked DOM navigation, image dialog, and three-state theme regressions passed. Native browser/visual/print acceptance not covered.');
