const announce=document.createElement('span');announce.setAttribute('role','status');announce.style.cssText='position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)';document.body.append(announce);
function copying(button,getText){const label=button.textContent;let timer;button.addEventListener('click',async()=>{clearTimeout(timer);try{await navigator.clipboard.writeText(getText());button.textContent='Copied';announce.textContent='Setup copied to clipboard.';}catch{const code=button.dataset.copyPanel?document.getElementById(button.dataset.copyPanel).querySelector('pre code'):document.getElementById('cmd');const range=document.createRange();range.selectNodeContents(code);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);button.textContent='Selected';announce.textContent='Clipboard unavailable. Select the command to copy it.';}timer=setTimeout(()=>{button.textContent=label;announce.textContent='';},2200);});}
copying(document.getElementById('copy'),()=>document.getElementById('cmd').textContent);
document.querySelectorAll('[data-copy-panel]').forEach(button=>copying(button,()=>document.getElementById(button.dataset.copyPanel).querySelector('pre code').textContent));
const tabs=[...document.querySelectorAll('[role="tab"]')];
function select(tab){tabs.forEach(item=>{const on=item===tab;item.setAttribute('aria-selected',String(on));item.tabIndex=on?0:-1;document.getElementById(item.getAttribute('aria-controls')).hidden=!on;});}
tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>select(tab));tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next!==undefined){event.preventDefault();select(tabs[next]);tabs[next].focus();}});});
const record=JSON.parse(document.getElementById('rehearsal-data').textContent);
const samples=[...document.querySelectorAll('[data-sample]')];
samples.forEach(button=>button.addEventListener('click',()=>{
  const key=button.dataset.sample;const prediction=key==='100';const point=prediction?record.prediction:record.samples.find(item=>item.key===key);
  samples.forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
  document.querySelectorAll('[data-chart-sample]').forEach(item=>item.dataset.selected=String(item.dataset.chartSample===key));
  document.getElementById('sample-name').textContent=prediction?'100% forecast':`${key}% rehearsal`;
  document.getElementById('sample-rows').textContent=point.rows.toLocaleString('en-US');
  document.getElementById('sample-detail').textContent=prediction?`${point.low.toLocaleString('en-US')}–${point.high.toLocaleString('en-US')} rows · estimated range`:`${point.seconds.toFixed(4)} s · observed`;
}));
