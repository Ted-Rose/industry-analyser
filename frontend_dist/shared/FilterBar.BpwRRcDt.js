import{m as p,r as c,j as e,t as a,B as h}from"./app.B5EiFZuK.js";/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const m={name:"chevron-right",size:24,node:[["path",{d:"m9 18 6-6-6-6",key:"mthhwq"}]]};m.node;const B=p(m);/**
 * @license lucide-react v1.65.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g={name:"sliders-horizontal",size:24,node:[["path",{d:"M10 5H3",key:"1qgfaw"}],["path",{d:"M12 19H3",key:"yhmn1j"}],["path",{d:"M14 3v4",key:"1sua03"}],["path",{d:"M16 17v4",key:"1q0r14"}],["path",{d:"M21 12h-9",key:"1o4lsq"}],["path",{d:"M21 19h-5",key:"1rlt1p"}],["path",{d:"M21 5h-7",key:"1oszz2"}],["path",{d:"M8 10v4",key:"tgpxqk"}],["path",{d:"M8 12H3",key:"a7s4jb"}]]};g.node;const q=p(g);function F({onSubmit:u,onReset:n,activeCount:o=0,collapsible:r=!1,actions:x,submitLabel:y="Apply",resetLabel:f="Reset",toggleLabel:b="Filters",children:k,className:j}){const d=c.useId(),[i,v]=c.useState(!1),t=r!==!1,l=r==="mobile",M=s=>{s.preventDefault(),u(s)},z=o>0?` (${o})`:"";return e.jsxs("form",{role:"search","aria-label":"Filters",onSubmit:M,className:a("rounded-lg border border-border bg-surface p-4 shadow-xs",j),children:[t&&e.jsxs("button",{type:"button","aria-expanded":i,"aria-controls":d,onClick:()=>v(s=>!s),className:a("inline-flex items-center gap-2 rounded-md px-2 py-2.5 text-sm font-medium text-fg-muted hover:bg-surface-2 hover:text-fg",l&&"md:hidden"),children:[e.jsx(q,{className:"size-4","aria-hidden":"true"}),`${b}${z}`]}),e.jsxs("div",{id:d,className:a("grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4",t&&"mt-3",t&&!i?"hidden":"grid",l&&"md:grid"),children:[k,e.jsxs("div",{className:`flex items-end gap-2 sm:col-span-2
            lg:col-span-4`,children:[e.jsx(h,{type:"submit",children:y}),n&&e.jsx(h,{type:"button",variant:"ghost",onClick:n,children:f}),x]})]})]})}export{B as C,F};
