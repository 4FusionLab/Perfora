// SPDX-License-Identifier: GPL-3.0-only
// Run in the connected Playwright tool. It opens its own tab, preserves the
// user's playground, and verifies live Python execution rather than fixtures.
async (page) => {
  const p=await page.context().newPage();
  const errors=[];p.on('pageerror',e=>errors.push(e.message));
  const results=[];
  const downloads=[];p.on('download',d=>downloads.push(d.suggestedFilename()));
  let stage='initialization';
  try {
    await p.goto('http://127.0.0.1:8768/demo/');
    await p.waitForFunction(()=>window.perforaDemo?.ready && document.querySelector('#status-text').textContent==='Live preview',null,{timeout:45000});
    const wait=()=>p.waitForFunction(()=>window.perforaDemo.ready && !window.perforaDemo.busy && document.querySelector('#status-text').textContent==='Live preview',null,{timeout:45000});
    const sample=async(label)=>{
      await wait();
      const result=await p.evaluate(async()=>{
        const r=window.perforaDemo.result;
        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(r.holes));
        return {parameters:window.perforaDemo.parameters,count:r.count,hash:[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join(''),center:r.first_center};
      });results.push({label,...result});
    };
    await sample('initial');
    for(const layout of ['staggered','rows','circular','path','contour','fan','phyllotaxis','poisson','wave','chevron','between_curves']){
      await p.locator('#layout').selectOption(layout);
      await p.waitForTimeout(250);
      await sample('layout-'+layout);
      if(layout==='path'){
        await p.locator('#show-guides').check();
        if(!await p.locator('#guide-geometry').isVisible())throw Error('Path guides did not appear.');
        await p.locator('#show-guides').uncheck();
      }
    }
    await p.locator('#layout').selectOption('chevron');
    const organic=new Set(['smooth_noise','reaction_diffusion','directional_fibers','topographic','gyroid','blue_noise']);
    for(const shape of ['circle','hexagon','square','slot','triangle','rectangle','diamond','ellipse','pentagon','octagon','cross','star','smooth_noise','reaction_diffusion','directional_fibers','topographic','gyroid','blue_noise','voronoi']){
      await p.locator('[data-mode="'+(organic.has(shape)?'organic':'pattern')+'"]').click();
      await p.locator('#shape').selectOption(shape);
      await p.waitForTimeout(250);
      await sample('shape-'+shape);
    }
    stage='family navigation';
    await p.locator('[data-mode="organic"]').click();
    await p.locator('#shape').selectOption('directional_fibers');await p.waitForTimeout(250);await sample('field-before-bridges');
    if(!await p.locator('#distribution-field').isHidden())throw Error('Field exposes Distribution.');
    if(await p.locator('#organic_bridges').isChecked())throw Error('Add Bridges defaults on.');
    const natural=results.at(-1).hash;
    await p.locator('#organic-fields summary').click();
    await p.locator('#organic_bridges').check();await p.waitForTimeout(250);await sample('field-with-bridges');
    if(results.at(-1).hash===natural)throw Error('Add Bridges did not alter the field.');
    const bridged=results.at(-1).hash;
    await p.locator('[data-mode="pattern"]').click();await p.waitForTimeout(250);await wait();
    if(!await p.locator('#organic-fields').isHidden())throw Error('Pattern exposes organic settings.');
    await p.locator('[data-mode="organic"]').click();await p.waitForTimeout(250);await sample('field-restored');
    if(results.at(-1).hash!==bridged||!await p.locator('#organic_bridges').isChecked())throw Error('Field settings lost on mode switch.');
    await p.locator('#reset').click();await p.waitForTimeout(250);await sample('reset');
    const original=results.at(-1).hash;
    await p.locator('#amplitude').fill('10');await p.locator('#amplitude').dispatchEvent('change');await p.waitForTimeout(250);await sample('changed-amplitude');
    if(results.at(-1).hash===original)throw Error('Changing amplitude did not alter geometry.');
    stage='shared link';
    await p.locator('#share').click();
    const shared=p.url();
    if(!shared.includes('#p='))throw Error('Share link did not encode the pattern.');
    await p.goto(shared);await wait();
    if(await p.locator('#amplitude').inputValue()!=='10')throw Error('Shared parameters were not restored.');
    stage='invalid input';await p.locator('#amplitude').fill('-1');await p.locator('#amplitude').dispatchEvent('change');
    await p.waitForFunction(()=>!document.querySelector('#error').hidden);
    await p.locator('#reset').click();await p.waitForTimeout(250);await wait();
    await p.locator('#browse').click();
    if(await p.locator('.pattern-tile').count()!==11)throw Error('Pattern gallery is incomplete.');
    stage='mobile';await p.setViewportSize({width:360,height:800});
    const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow)throw Error('Mobile layout overflows.');
    if(errors.length)throw Error(errors.join('\n'));
    return {passed:true,results,mobileOverflow:overflow,consoleErrors:errors};
  } catch(error){return {passed:false,stage,error:error.message,errors,downloads,results};}
  finally {await p.close();}
}
