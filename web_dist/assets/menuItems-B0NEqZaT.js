function i(...o){return o.filter(e=>e.length>0).flatMap((e,a)=>e.map((r,n)=>({...r,dividerBefore:!!(r.dividerBefore||a>0&&n===0)})))}export{i as a};
