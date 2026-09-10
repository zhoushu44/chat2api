import{q as V,d as ve,H as me,c,l as o,w as n,m as l,p as x,j as u,o as r,a,y as h,b as v,t as i,a9 as B,aa as F,e as m,F as N,r as O,D as ge,k as f,u as he,U as fe}from"./index-B1U1MKOr.js";import{_ as be}from"./TableShell.vue_vue_type_style_index_0_scoped_48f93359_lang-dmCKYlWc.js";import{C as H}from"./CodeBlock-MSD_Oxja.js";import{C as _e}from"./ConsoleSegmentedTabs-BMKpQnZ0.js";import{P as E}from"./PagePanel-D-5K6DFX.js";import{P as L}from"./PanelHeader-CNe-gHdm.js";import{S as te}from"./StateBadge-CG65fjGn.js";function ke(d="debug"){return typeof crypto<"u"&&typeof crypto.randomUUID=="function"?`${d}-${crypto.randomUUID()}`:`${d}-${Date.now()}-${Math.random().toString(16).slice(2)}`}function ye(d){return d==="psd"?"/v1/psd/generations":"/v1/ppt/generations"}const R={search:async d=>V.post("/v1/search",{prompt:d}),chat:async(d,g)=>V.post("/v1/chat/completions",{model:d.trim()||"auto",messages:g}),createEditableFileTask:async(d,g)=>{const p={client_task_id:ke(d),prompt:g.prompt,base64_images:g.base64_images||[]};return V.post(ye(d),p)},listEditableFileTasks:async d=>{const g=d?.length?{ids:d.join(",")}:void 0;return V.get("/v1/editable-file-tasks",{params:g})}},we={class:"debug-center space-y-5"},xe={key:0,class:"debug-error"},Ce={key:1,class:"debug-result-grid"},Pe={class:"debug-result-card"},Se={class:"debug-result-meta"},Te={class:"debug-answer"},Ie={key:0,class:"debug-result-card"},$e=["href"],Ue={class:"truncate"},Ee={class:"truncate text-muted-foreground"},Le={class:"grid gap-4 lg:grid-cols-2"},ze={class:"grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]"},De={class:"space-y-3"},Ve={key:0,class:"debug-error"},Be={class:"debug-task-list"},Fe={key:0,class:"debug-empty"},Re={class:"flex flex-wrap items-center gap-2"},qe={class:"font-mono text-[11px] text-muted-foreground"},Ae={class:"mt-2 text-sm text-foreground"},Ke={key:0,class:"mt-2 text-xs text-rose-600"},Me={key:1,class:"mt-3 flex flex-wrap gap-2"},Ne={class:"grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]"},Oe={class:"space-y-3"},He={key:0,class:"debug-error"},je={class:"debug-chat-box"},Je={key:0,class:"debug-empty"},Ze={class:"ui-section-kicker"},Ge={class:"whitespace-pre-wrap text-sm leading-7 text-foreground"},Qe=ve({__name:"DebugCenter",setup(d){const g=he(),p=u("search"),ae=[{label:"搜索",value:"search"},{label:"Skills 搜索",value:"skills"},{label:"PPT 生成",value:"ppt"},{label:"PSD 生成",value:"psd"},{label:"对话",value:"chat"}],z=u("帮我搜索 chatgpt2api 相关项目"),b=u(null),D=u(""),C=u(!1),j=u(0),se=f(()=>`${(j.value/1e3).toFixed(2)}s`),q=u("auto"),P=u("你好，先记住我的项目叫 chatgpt2api。"),k=u([]),A=u(null),S=u(!1),T=u(""),le=f(()=>JSON.stringify(A.value||{messages:[]},null,2)),y=u(""),K=u(""),I=u([]),$=u(!1),U=u(!1),w=u(""),J=f(()=>window.location.origin.replace(/\/$/,"")),Z=f(()=>fe()),re=f(()=>`---
name: chatgpt2api-search
description: 当用户需要联网搜索、查询最新信息、核实事实或需要来源链接时，调用本地 chatgpt2api 搜索接口。
---

# ChatGPT2API 搜索

当用户要求联网搜索、查询最新信息、核实资料、查新闻、查价格、查文档更新或需要来源链接时，使用这个 skill。

## 接口

POST ${J.value}/v1/search

Headers:

Authorization: Bearer ${Z.value}
Content-Type: application/json

Body:

{
  "prompt": "<用户要搜索的问题>"
}

## 返回处理

- 使用接口返回的 \`answer\` 作为主要回答。
- 如果有 \`sources\`，在回答里附上来源链接。
- 如果接口报错，简要说明错误并询问是否重试。`),ne=f(()=>`---
name: chatgpt2api-search
description: Use when current web search is needed through this chatgpt2api server. Call the configured HTTP search endpoint with a prompt and return the answer with source URLs.
---

# ChatGPT2API Search

Use this skill when the user asks for current web search, online lookup, recent information, or source-backed answers.

## Request

POST ${J.value}/v1/search

Headers:

Authorization: Bearer ${Z.value}
Content-Type: application/json

JSON body:

{
  "prompt": "<search question>"
}

## Response handling

- Use \`answer\` as the main response.
- Include source URLs from \`sources\` when available.
- If the endpoint returns an error, summarize the error and ask whether to retry.`),G=f(()=>`请帮我在本机安装一个用于联网搜索的 skill。

要求：
1. 按当前环境的 skill 安装规范，把它安装成本地 skill。
2. skill 名称为：chatgpt2api-search
3. 文件名为：SKILL.md
4. 只创建或更新这个 skill 文件，不要修改其他无关文件。

SKILL.md 内容：

\`\`\`markdown
${re.value}
\`\`\``),Q=f(()=>`Please install a local web-search skill on this machine.

Requirements:
1. Install this as a local skill according to the current environment's skill rules.
2. Skill name: chatgpt2api-search
3. File name: SKILL.md
4. Only create or update this skill file.

SKILL.md content:

\`\`\`markdown
${ne.value}
\`\`\``),W=f(()=>p.value==="psd"?"psd":"ppt");me(p,s=>{s==="ppt"?(y.value="生成一个 chatgpt2api 项目架构说明 PPT，包含后端链路、前端控制台、账号池、日志和图片链路。",M()):s==="psd"&&(y.value="生成一个适合控制台产品展示的 PSD 版式，包含概览、账号、日志、图片和代理管理区块。",M())},{immediate:!0});async function X(s){try{await navigator.clipboard.writeText(s),g.success("已复制")}catch{g.error("复制失败")}}async function oe(){const s=z.value.trim();if(!s||C.value)return;const e=Date.now();C.value=!0,D.value="",b.value=null;try{b.value=await R.search(s)}catch(t){D.value=t?.message||"搜索失败"}finally{j.value=Date.now()-e,C.value=!1}}async function ie(){const s=P.value.trim();if(!s||S.value)return;const e=[...k.value,{role:"user",content:s}];k.value=e,P.value="",S.value=!0,T.value="";try{const t=await R.chat(q.value,e);A.value=t,k.value=[...e,{role:"assistant",content:String(t.choices?.[0]?.message?.content||"")}]}catch(t){T.value=t?.message||"发送失败"}finally{S.value=!1}}function ue(){k.value=[],A.value=null,T.value=""}function Y(s){return String(s.taskId||s.id||"")}function ce(s){const e=String(s||"queued");return{queued:"排队中",running:"生成中",success:"已完成",error:"失败"}[e]||e}function de(s){const e=String(s||"").toLowerCase();return e==="success"?"success":e==="error"?"danger":e==="queued"||e==="running"?"warning":"muted"}async function M(){if(!U.value){U.value=!0,w.value="";try{const s=await R.listEditableFileTasks();I.value=(s.items||[]).filter(e=>e.kind===W.value).slice(0,20)}catch(s){w.value=s?.message||"任务加载失败"}finally{U.value=!1}}}async function pe(){const s=y.value.trim();if(!(!s||$.value)){$.value=!0,w.value="";try{const e=K.value.split(/\r?\n/).map(_=>_.trim()).filter(Boolean),t=await R.createEditableFileTask(W.value,{prompt:s,base64_images:e});I.value=[t,...I.value].slice(0,20),g.success("任务已提交")}catch(e){w.value=e?.message||"提交失败"}finally{$.value=!1}}}function ee(s){window.open(s,"_blank","noopener,noreferrer")}return(s,e)=>(r(),c("div",we,[o(l(E),{class:"debug-center__panel"},{default:n(()=>[o(l(L),{title:"调试中心"},{copy:n(()=>[...e[8]||(e[8]=[a("p",{class:"mt-1 text-xs text-muted-foreground"},"搜索、Skills、PPT、PSD、对话这些旧调试工具集中在这里。",-1)])]),_:1}),o(l(_e),{modelValue:p.value,"onUpdate:modelValue":e[0]||(e[0]=t=>p.value=t),options:ae,"aria-label":"调试工具"},null,8,["modelValue"])]),_:1}),p.value==="search"?(r(),x(l(E),{key:0,class:"debug-center__panel"},{default:n(()=>[o(l(L),{title:"搜索"},{actions:n(()=>[o(l(h),{size:"sm",variant:"primary",disabled:C.value||!z.value.trim(),onClick:oe},{default:n(()=>[v(i(C.value?"搜索中...":"开始搜索"),1)]),_:1},8,["disabled"])]),_:1}),B(a("textarea",{"onUpdate:modelValue":e[1]||(e[1]=t=>z.value=t),class:"debug-textarea",rows:"4",placeholder:"输入要搜索的问题"},null,512),[[F,z.value,void 0,{trim:!0}]]),D.value?(r(),c("div",xe,i(D.value),1)):m("",!0),b.value?(r(),c("div",Ce,[a("div",Pe,[a("div",Se,[o(l(te),{tone:"success",shape:"rounded",bordered:!1},{default:n(()=>[v(i(b.value.status||"done"),1)]),_:1}),a("span",null,i(se.value),1),a("span",null,i(b.value.sources?.length||0)+" sources",1)]),a("div",Te,i(b.value.answer||"-"),1)]),b.value.sources?.length?(r(),c("div",Ie,[e[9]||(e[9]=a("p",{class:"ui-section-kicker"},"来源",-1)),(r(!0),c(N,null,O(b.value.sources,(t,_)=>(r(),c("a",{key:`${t.url||_}`,class:"debug-source-link",href:t.url,target:"_blank",rel:"noopener noreferrer"},[a("span",Ue,i(t.title||t.url||"source"),1),a("span",Ee,i(t.url),1)],8,$e))),128))])):m("",!0)])):m("",!0)]),_:1})):p.value==="skills"?(r(),x(l(E),{key:1,class:"debug-center__panel"},{default:n(()=>[o(l(L),{title:"Skills 搜索"},{actions:n(()=>[o(l(h),{size:"sm",variant:"outline",onClick:e[2]||(e[2]=t=>X(G.value))},{default:n(()=>[...e[10]||(e[10]=[v("复制中文安装指令",-1)])]),_:1}),o(l(h),{size:"sm",variant:"outline",onClick:e[3]||(e[3]=t=>X(Q.value))},{default:n(()=>[...e[11]||(e[11]=[v("复制英文安装指令",-1)])]),_:1})]),_:1}),a("div",Le,[a("div",null,[e[12]||(e[12]=a("p",{class:"ui-section-kicker"},"中文安装指令",-1)),o(l(H),{content:G.value},null,8,["content"])]),a("div",null,[e[13]||(e[13]=a("p",{class:"ui-section-kicker"},"English install prompt",-1)),o(l(H),{content:Q.value},null,8,["content"])])])]),_:1})):p.value==="ppt"||p.value==="psd"?(r(),x(l(E),{key:2,class:"debug-center__panel"},{default:n(()=>[o(l(L),{title:p.value==="ppt"?"PPT 生成":"PSD 生成"},{actions:n(()=>[o(l(h),{size:"sm",variant:"outline",disabled:U.value,onClick:M},{default:n(()=>[v(i(U.value?"刷新中...":"刷新任务"),1)]),_:1},8,["disabled"]),o(l(h),{size:"sm",variant:"primary",disabled:$.value||!y.value.trim(),onClick:pe},{default:n(()=>[v(i($.value?"提交中...":"提交任务"),1)]),_:1},8,["disabled"])]),_:1},8,["title"]),a("div",ze,[a("div",De,[B(a("textarea",{"onUpdate:modelValue":e[4]||(e[4]=t=>y.value=t),class:"debug-textarea",rows:"9",placeholder:"输入生成要求"},null,512),[[F,y.value,void 0,{trim:!0}]]),B(a("textarea",{"onUpdate:modelValue":e[5]||(e[5]=t=>K.value=t),class:"debug-textarea debug-textarea--small",rows:"4",placeholder:"可选：每行一个 base64/data:image 参考图"},null,512),[[F,K.value,void 0,{trim:!0}]]),w.value?(r(),c("div",Ve,i(w.value),1)):m("",!0)]),a("div",Be,[I.value.length===0?(r(),c("div",Fe,"暂无任务")):m("",!0),(r(!0),c(N,null,O(I.value,t=>(r(),c("article",{key:Y(t),class:"debug-task-card"},[a("div",Re,[o(l(te),{tone:de(t.status),shape:"rounded",bordered:!1},{default:n(()=>[v(i(ce(t.status)),1)]),_:2},1032,["tone"]),a("span",qe,i(Y(t)),1)]),a("p",Ae,i(t.prompt_preview||"-"),1),t.error?(r(),c("p",Ke,i(t.error),1)):m("",!0),t.result?.primary_url||t.result?.zip_url?(r(),c("div",Me,[t.result?.primary_url?(r(),x(l(h),{key:0,size:"xs",variant:"outline",onClick:_=>ee(t.result.primary_url)},{default:n(()=>[...e[14]||(e[14]=[v("打开结果",-1)])]),_:1},8,["onClick"])):m("",!0),t.result?.zip_url?(r(),x(l(h),{key:1,size:"xs",variant:"outline",onClick:_=>ee(t.result.zip_url)},{default:n(()=>[...e[15]||(e[15]=[v("下载 ZIP",-1)])]),_:1},8,["onClick"])):m("",!0)])):m("",!0)]))),128))])])]),_:1})):(r(),x(l(E),{key:3,class:"debug-center__panel"},{default:n(()=>[o(l(L),{title:"对话"},{actions:n(()=>[o(l(h),{size:"sm",variant:"outline",onClick:ue},{default:n(()=>[...e[16]||(e[16]=[v("清空",-1)])]),_:1}),o(l(h),{size:"sm",variant:"primary",disabled:S.value||!P.value.trim(),onClick:ie},{default:n(()=>[v(i(S.value?"发送中...":"发送"),1)]),_:1},8,["disabled"])]),_:1}),a("div",Ne,[a("div",Oe,[o(l(ge),{modelValue:q.value,"onUpdate:modelValue":e[6]||(e[6]=t=>q.value=t),modelModifiers:{trim:!0},type:"text",placeholder:"model，例如 auto",block:""},null,8,["modelValue"]),B(a("textarea",{"onUpdate:modelValue":e[7]||(e[7]=t=>P.value=t),class:"debug-textarea",rows:"8",placeholder:"输入消息"},null,512),[[F,P.value,void 0,{trim:!0}]]),T.value?(r(),c("div",He,i(T.value),1)):m("",!0),o(l(H),{content:le.value},null,8,["content"])]),a("div",je,[k.value.length===0?(r(),c("div",Je,"暂无对话消息")):m("",!0),(r(!0),c(N,null,O(k.value,(t,_)=>(r(),c("article",{key:`${t.role}-${_}`,class:"debug-chat-message"},[a("p",Ze,i(t.role),1),a("p",Ge,i(t.content),1)]))),128))])])]),_:1}))]))}}),lt=be(Qe,[["__scopeId","data-v-62bc0c0a"]]);export{lt as default};
