// Pure frontend regression checks; no production files or NAS are changed.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../templates/location-dashboard.html'),'utf8');
const script=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
new vm.Script(script); // Check syntax of the complete shipped application.
function functionSource(name){
  const start=script.indexOf(`    function ${name}(`);
  assert(start>=0,`missing ${name}`);
  const end=script.indexOf('\n    ',start+5);
  return script.slice(start,end<0?undefined:end);
}
const controls={'compare-search':{value:''},'compare-state':{value:'diff'},'compare-category':{value:''}};
const boxes=[{dataset:{syncSelect:'a.txt'},disabled:false,getClientRects:()=>[{}]},
  {dataset:{syncSelect:'hidden.txt'},disabled:false,getClientRects:()=>[]},
  {dataset:{syncSelect:'disabled.txt'},disabled:true,getClientRects:()=>[{}]}];
const context={DATA:{files:[{relative:'a.txt',name:'a.txt',extension:'.txt',state:'COMPUTER_ONLY'},
  {relative:'b.txt',name:'b.txt',extension:'.txt',state:'BOTH_SAME'},
  {relative:'folder/c.txt',name:'c.txt',extension:'.txt',state:'NAS_ONLY'}]},
  el:id=>controls[id],displayPath:p=>p,activeSyncId:'',selectedForSync:new Set(),selectedFolders:new Set(['folder']),
  document:{querySelectorAll:()=>boxes},updateSyncPanel:()=>{}};
vm.createContext(context);
// Multiline functions are bounded by the next function declaration.
for(const name of ['compareExportRows','csvCell','selectVisibleCompareFiles','clearFileSelection']){
  const start=script.indexOf(`    function ${name}(`);
  const next=script.indexOf('\n    function ',start+5);
  const boundary=script.indexOf('\n    const compareTools=',start+5);
  const end=Math.min(...[next,boundary].filter(x=>x>=0));
  vm.runInContext(script.slice(start,end),context);
}
assert.equal(context.compareExportRows().length,2);
controls['compare-category'].value='folder';assert.equal(context.compareExportRows()[0].relative,'folder/c.txt');
controls['compare-search'].value='not found';assert.equal(context.compareExportRows().length,0);
assert.equal(context.csvCell('a,"b'), '"a,""b"');
assert.equal(context.csvCell('=SUM(1,2)'), '"\'=SUM(1,2)"');
context.selectVisibleCompareFiles();assert.deepEqual([...context.selectedForSync],['a.txt']);
context.activeSyncId='running';context.clearFileSelection();assert.equal(context.selectedForSync.size,1);
context.activeSyncId='';context.clearFileSelection();assert.equal(context.selectedForSync.size,0);assert.equal(context.selectedFolders.size,0);
assert(script.includes('await reloadDirectoryData()'));
assert(!script.includes('重新打开页面查看最新目录'));
assert(script.includes("openButton('nas',f.relative,'打开 NAS 目录')"));
assert(script.includes('本地覆盖 NAS</button>'));
assert(script.includes('NAS 覆盖本地</button>'));
assert(!script.includes('syncToast(`${actionName} 已开始'));
console.log('PASS: full script syntax, filtered export, CSV escaping, formula protection, visible-only selection, busy guard, clear selection, in-place refresh wiring');
