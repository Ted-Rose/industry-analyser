import{n as t,G as l,j as e,T as d,H as m,r as u}from"./sentry.D1D0ydFY.js";/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const n={name:"circle-alert",size:24,node:[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["line",{x1:"12",x2:"12",y1:"8",y2:"12",key:"1pkeuh"}],["line",{x1:"12",x2:"12.01",y1:"16",y2:"16",key:"4dfq90"}]],aliases:["alert-circle"]};n.node;const x=t(n);/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const c={name:"circle-check",size:24,node:[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m16 9-5.5 5.5L8 12",key:"xofnsj"}]],aliases:["check-circle-2"]};c.node;const y=t(c);/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const i={name:"info",size:24,node:[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"M12 16v-4",key:"1dtifu"}],["path",{d:"M12 8h.01",key:"e9boi3"}]]};i.node;const h=t(i);/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const o={name:"x",size:24,node:[["path",{d:"M18 6 6 18",key:"1bl5f8"}],["path",{d:"m6 6 12 12",key:"d8bk6v"}]]};o.node;const k=t(o),p={success:y,danger:x,warning:d,info:h};function f(){const s=l();return s.length===0?null:e.jsx("div",{className:"ia-toasts",children:s.map(a=>{const r=p[a.kind];return e.jsxs("div",{className:`ia-toast ia-toast--${a.kind}`,role:"alert",children:[e.jsx("span",{className:"ia-toast__icon","aria-hidden":"true",children:e.jsx(r,{size:16})}),e.jsx("span",{className:"ia-toast__text",children:a.text}),e.jsx("button",{type:"button",className:"ia-toast__dismiss","aria-label":"Dismiss",onClick:()=>m(a.id),children:e.jsx(k,{size:14,"aria-hidden":"true"})})]},a.id)})})}function j(){return u.useMemo(()=>{const s=document.getElementById("spa-bootstrap");if(!s||!s.textContent)return{};try{return JSON.parse(s.textContent)}catch{return{}}},[])}export{x as C,h as I,f as T,k as X,y as a,j as u};
