// SPDX-License-Identifier: GPL-3.0-only
(() => {
  'use strict';
  const bundle=JSON.parse(document.getElementById('demo-bundle').textContent);
  const $=id=>document.getElementById(id);
  const fields=[...document.querySelectorAll('[data-parameter]')];
  const defaults=Object.fromEntries(fields.map(el=>[el.id,el.type==='checkbox'?el.checked:el.value]));
  const organics=new Set(['smooth_noise','reaction_diffusion','directional_fibers','topographic','gyroid','blue_noise']);
  const lengths=new Set(['slot','ellipse','rectangle','diamond']);
  const descriptions={staggered:'Offset rows. A classic, balanced rhythm.',rows:'Straight rows and columns. Clean and precise.',circular:'Concentric rings, filled from the center.',path:'One continuous row along a guide curve.',contour:'Closed rows that follow the panel boundary.',fan:'Unbroken rays with a shared inner arc.',phyllotaxis:'The golden angle. A sunflower’s natural rhythm.',poisson:'An irregular field, with a consistent minimum gap.',wave:'Smooth, continuous rows. A rhythm that flows.',chevron:'Mirrored rows. A clear directional pattern.',between_curves:'Aligned rows between two flowing guides.'};
  const sizeLabels={circle:'Diameter',hexagon:'Across Flats',square:'Side Length',slot:'Width',triangle:'Side Length',rectangle:'Width',diamond:'Diagonal 1',ellipse:'Minor Axis',pentagon:'Diameter',octagon:'Across Flats',cross:'Overall Size',star:'Outer Diameter',voronoi:'Cell Spacing'};
  let worker,ready=false,busy=false,latestId=0,wanted=null,current=null,currentParameters=null,timer,watchdog,workerGeneration=0;
  const cache=new Map();
  const familySettings={};
  let activeFamily='pattern';
  function parameters(){return Object.fromEntries(fields.map(el=>[el.id,el.type==='checkbox'?el.checked:el.tagName==='SELECT'?el.value:Number(el.value)]));}
  function status(message,mode='ready'){$('status-text').textContent=message;$('status-dot').className='status-dot'+(mode==='ready'?'':' '+mode);}
  function visibility(){
    const layout=$('layout').value,shape=$('shape').value,voronoi=shape==='voronoi',organic=organics.has(shape),field=voronoi||organic;
    const family=field?'organic':'pattern';activeFamily=family;
    $('distribution-field').hidden=field;
    $('layout-help').hidden=field;
    $('shape-label').textContent=field?'Field':'Hole Shape';
    $('mode-caption').textContent=field?'Organic and cellular openings. Size and web define the pattern.':'Choose a shape and arrange it.';
    for(const option of $('shape').options)option.hidden=(organics.has(option.value)||option.value==='voronoi')!==field;
    for(const button of document.querySelectorAll('[data-mode]'))button.setAttribute('aria-pressed',String(button.dataset.mode===family));
    $('layout').disabled=field;
    $('layout-help').textContent=organic?'This shape creates its own field. Pattern Scale sets its physical size.':voronoi?'Organic polygonal cells. One field, its own distribution.':descriptions[layout];
    $('size-label').textContent=organic?(shape==='blue_noise'?'Maximum Diameter':'Cell Size'):sizeLabels[shape];
    $('length-field').hidden=!lengths.has(shape);
    $('length-field').firstChild.textContent=shape==='ellipse'?'Major Axis':shape==='diamond'?'Diagonal 2':'Length';
    $('orientation-field').hidden=field||shape==='circle'||['staggered','rows','poisson'].includes(layout);
    $('radial-option').hidden=layout!=='circular';
    if(layout!=='circular'&&$('orientation').value==='radial')$('orientation').value='tangent';
    $('seed-field').hidden=!(field||layout==='poisson');
    $('spacing-field').hidden=field||!bundle.variants.includes(layout);
    $('angle-field').hidden=field||shape==='circle';
    $('arm-field').hidden=shape!=='cross';
    $('star-points-field').hidden=$('star-ratio-field').hidden=shape!=='star';
    $('irregularity-field').hidden=$('corners-field').hidden=!voronoi;
    for(const field of document.querySelectorAll('[data-for]'))field.hidden=voronoi||organic||field.dataset.for!==layout;
    $('spacing-value').textContent=Number($('spacing').value).toFixed(2)+'×';
    const disk=$('boundary').value==='disk';
    $('height').closest('label').hidden=disk;
    $('width').closest('label').firstChild.textContent=disk?'Diameter':'Width';
    document.querySelectorAll('.pattern-tile').forEach(el=>el.setAttribute('aria-pressed',String(!voronoi&&el.dataset.layout===layout)));
    $('show-guides').disabled=field;
    $('organic-fields').hidden=!organic;
    $('organic-bridges-field').hidden=shape==='blue_noise';
    $('pattern-options').hidden=organic;
    $('organic-variation-field').hidden=$('organic-gradient-field').hidden=shape!=='blue_noise';
  }
  function setValues(values){
    for(const el of fields){
      if(!(el.id in values))continue;
      const value=String(values[el.id]);
      if(el.tagName==='SELECT'&&![...el.options].some(o=>o.value===value))continue;
      if(el.type==='checkbox')el.checked=Boolean(values[el.id]);else el.value=value;
    }
    visibility();
  }
  function scaleBar(){
    const svg=$('preview'),box=svg.viewBox.baseVal,r=svg.getBoundingClientRect();
    const unit=Math.min(r.width/box.width,r.height/box.height);
    document.querySelector('.scale-note>span').style.width=unit+'px';
  }
  function render(result,config){
    current=result;currentParameters={...config};
    const [x,y,w,h]=result.box,pad=Math.max(w,h)*.13;
    $('preview').setAttribute('viewBox',`${x-pad} ${y-pad} ${w+pad*2} ${h+pad*2}`);
    $('preview').setAttribute('aria-label',`${organics.has(config.shape)||config.shape==='voronoi'?$('shape').selectedOptions[0].textContent:$('layout').selectedOptions[0].textContent} pattern, ${result.count} holes, ${result.open_area}% open area`);
    $('panel-geometry').innerHTML=result.clip?`<defs><clipPath id="cut-boundary"><path d="${result.clip}"/></clipPath><mask id="panel-cut" maskUnits="userSpaceOnUse" x="${x}" y="${y}" width="${w}" height="${h}"><path d="${result.outer}" fill="white"/><path d="${result.holes}" fill="black" clip-path="url(#cut-boundary)"/></mask></defs><path d="${result.outer}" fill="#343c38" mask="url(#panel-cut)" filter="url(#panel-shadow)"/>`:`<path d="${result.outer} ${result.holes}" fill="#343c38" fill-rule="evenodd" filter="url(#panel-shadow)"/>`;
    $('guide-geometry').innerHTML=result.guides.map(d=>`<path d="${d}"/>`).join('');
    $('guide-geometry').toggleAttribute('hidden',!$('show-guides').checked);
    $('show-guides').closest('label').hidden=!result.guides.length;
    $('hole-count').textContent=result.count.toLocaleString();
    $('open-area').textContent=result.open_area.toFixed(1)+'%';
    $('dimension-caption').textContent=(config.boundary==='disk'?`Ø ${config.width}`:`${config.width} × ${config.height}`)+' mm';
    $('error').hidden=true;
    scaleBar();
  }
  function fail(message){
    $('error').textContent=message;
    $('error').hidden=false;
    status(ready?'Adjust the pattern settings':'Live controls unavailable','failed');
  }
  function sendNext(){
    if(!ready||busy||!wanted)return;
    const job=wanted;wanted=null;
    if(cache.has(job.key)){
      render(cache.get(job.key),job.parameters);status('Live preview');return;
    }
    busy=true;status('Updating preview…','loading');
    worker.postMessage({type:'compute',id:job.id,parameters:job.parameters});
    watchdog=setTimeout(()=>{
      worker.terminate();workerGeneration++;ready=false;busy=false;
      fail('This pattern took too long. Use larger holes, a wider web or a smaller panel, then retry.');
      addRetry();
    },45000);
  }
  function schedule(){
    clearTimeout(timer);visibility();
    const invalid=fields.find(el=>!el.disabled&&!el.closest('[hidden]')&&!el.checkValidity());
    if(invalid){fail('Check '+(invalid.closest('label')?.textContent.trim().split('\n')[0]||'the highlighted value')+'.');return;}
    const config=parameters();latestId++;
    wanted={id:latestId,key:JSON.stringify(config),parameters:config};
    if(!ready){status('Preparing live controls…','loading');return;}
    status('Updating preview…','loading');
    timer=setTimeout(sendNext,200);
  }
  function addRetry(){
    if($('retry'))return;
    const button=document.createElement('button');button.id='retry';button.type='button';button.className='secondary';button.textContent='Retry live controls';
    button.addEventListener('click',()=>{button.remove();$('error').hidden=true;startWorker();});
    $('error').append(document.createElement('br'),button);
  }
  function startWorker(){
    if(worker)worker.terminate();
    ready=false;busy=false;
    const generation=++workerGeneration;
    status('Preparing live controls…','loading');
    const url=URL.createObjectURL(new Blob([bundle.worker],{type:'text/javascript'}));
    try{worker=new Worker(url);}catch(error){URL.revokeObjectURL(url);fail('Your browser could not start live controls. Try a current browser with JavaScript enabled.');return;}
    URL.revokeObjectURL(url);
    worker.onmessage=({data})=>{
      if(generation!==workerGeneration)return;
      if(data.type==='ready'){
        ready=true;status('Live preview');schedule();
      }else if(data.type==='result'){
        clearTimeout(watchdog);busy=false;
        if(data.id===latestId){
          const config=parameters();cache.set(JSON.stringify(config),data.result);
          if(cache.size>24)cache.delete(cache.keys().next().value);
          render(data.result,config);status('Live preview');
        }
        sendNext();
      }else if(data.type==='error'){
        clearTimeout(watchdog);busy=false;
        const message=data.message.split('\n').filter(Boolean).pop().replace(/^\w*Error:\s*/,'');
        if(data.id){if(data.id===latestId)fail(message);sendNext();}
        else{ready=false;fail('Live controls could not load. An internet connection is needed for the first launch.');addRetry();}
      }
    };
    worker.onerror=()=>{clearTimeout(watchdog);busy=false;ready=false;fail('Live controls could not start. Check your connection and retry.');addRetry();};
    worker.postMessage({type:'init',sources:bundle.sources});
  }
  // Start the debounce while typing, keeping geometry and input in sync
  // before the user moves focus to another control.
  for(const el of fields)el.addEventListener(el.tagName==='SELECT'?'change':'input',()=>{
    if(el.id==='shape'){
      const sh=el.value;
      if(sh==='slot'){$('size').value='1.7';$('length').value='5.2';}
      else if(sh==='voronoi')$('size').value='7';
      else if(organics.has(sh))$('size').value='8';
      else $('size').value='2.5';
      if(sh==='cross')$('arm_width').value='.8';
    }
    schedule();
  });
  document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{
    const family=button.dataset.mode;if(family===activeFamily)return;
    familySettings[activeFamily]=parameters();
    const panel={width:$('width').value,height:$('height').value,boundary:$('boundary').value};
    setValues({...defaults,...(familySettings[family]||{shape:family==='organic'?'smooth_noise':'slot',size:family==='organic'?8:1.7,gap:family==='organic'?.8:1.2}),...panel});
    schedule();
  }));
  $('new-seed').addEventListener('click',()=>{$('seed').value=(Number($('seed').value)+1)%2147483648;schedule();});
  $('reset').addEventListener('click',()=>{setValues(defaults);history.replaceState(null,'',location.pathname+location.search);schedule();});
  $('show-guides').addEventListener('change',()=>{$('guide-geometry').toggleAttribute('hidden',!$('show-guides').checked);});
  $('browse').addEventListener('click',()=>{const visible=$('pattern-gallery').hidden;$('pattern-gallery').hidden=!visible;$('browse').setAttribute('aria-expanded',String(visible));$('browse').textContent=visible?'Close patterns ↗':'Explore patterns ↘';});
  document.querySelectorAll('.pattern-tile').forEach(button=>button.addEventListener('click',()=>{
    $('layout').value=button.dataset.layout;
    if($('shape').value==='voronoi'||organics.has($('shape').value)){$('shape').value='circle';$('size').value='2.5';}
    $('boundary').value=button.dataset.layout==='contour'?'rounded':button.dataset.layout==='phyllotaxis'?'disk':'rectangle';
    schedule();
  }));
  document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>{
    setValues(defaults);
    if(button.dataset.preset==='sunflower')setValues({layout:'phyllotaxis',shape:'circle',size:2.5,boundary:'disk'});
    if(button.dataset.preset==='honeycomb')setValues({layout:'staggered',shape:'hexagon',size:4,gap:1,boundary:'rectangle'});
    schedule();
  }));
  $('share').addEventListener('click',async()=>{
    const hash='#p='+encodeURIComponent(JSON.stringify(parameters()));
    history.replaceState(null,'',location.pathname+location.search+hash);
    try{await navigator.clipboard.writeText(location.href);$('share').textContent='Link copied ✓';setTimeout(()=>$('share').textContent='Copy pattern link ↗',1800);}
    catch{ $('share-fallback').hidden=false;$('share-url').value=location.href;$('share-url').select(); }
  });
  if(location.hash.startsWith('#p=')){
    try{const data=JSON.parse(decodeURIComponent(location.hash.slice(3)));if(data&&typeof data==='object')setValues(data);}catch{/* Keep useful defaults for a malformed shared link. */}
  }
  visibility();
  render(bundle.initial,defaults);
  startWorker();
  new ResizeObserver(scaleBar).observe($('preview-stage'));
  // A narrow read-only hook makes public-kernel parity and controls testable.
  window.perforaDemo={get parameters(){return parameters();},get result(){return current;},get ready(){return ready;},get busy(){return busy;},source:bundle.source};
})();
