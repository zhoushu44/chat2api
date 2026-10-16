import{d as pe,n as me,c as i,b as n,f as r,B as y,r as u,o as l,a,e as v,g as m,h as d,t as o,a7 as L,a8 as U,x as c,F as B,A as D,k as ge,ao as he,D as g,j as fe,L as be}from"./index-D1CpqPtV.js";import{C as N}from"./CodeBlock-DizLG1AD.js";import{C as _e}from"./ConsoleSegmentedTabs-DHamFXRF.js";import{P as E}from"./PagePanel-CkMPX79m.js";import{P as z}from"./PanelHeader-DaX6CDQz.js";import{S as ee}from"./StateBadge-B0xjTDzk.js";import{d as R}from"./debug-ApaPeik0.js";import{_ as ke}from"./_plugin-vue_export-helper-DlAUqK2U.js";import"./MetaChip.vue_vue_type_script_setup_true_lang-DscmMIOD.js";const ye={class:"debug-center space-y-5"},we={key:0,class:"debug-error"},xe={key:1,class:"debug-result-grid"},Pe={class:"debug-result-card"},Se={class:"debug-result-meta"},Ce={class:"debug-answer"},Te={key:0,class:"debug-result-card"},Ie=["href"],Le={class:"truncate"},Ee={class:"truncate text-muted-foreground"},ze={class:"grid gap-4 lg:grid-cols-2"},Ve={class:"grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]"},$e={class:"space-y-3"},Ue={key:0,class:"debug-error"},Be={class:"debug-task-list"},De={key:0,class:"debug-empty"},Re={class:"flex flex-wrap items-center gap-2"},Ae={class:"font-mono text-[11px] text-muted-foreground"},Fe={class:"mt-2 text-sm text-foreground"},Me={key:0,class:"mt-2 text-xs text-rose-600"},Oe={key:1,class:"mt-3 flex flex-wrap gap-2"},qe={class:"grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]"},Ke={class:"space-y-3"},Ne=["value"],He={key:0,class:"debug-error"},je={class:"debug-chat-box"},Je={key:0,class:"debug-empty"},Ze={class:"ui-section-kicker"},Ge={class:"whitespace-pre-wrap text-sm leading-7 text-foreground"},Qe=pe({__name:"DebugCenter",setup(We){const A=fe(),p=u("search"),te=[{label:"搜索",value:"search"},{label:"Skills 搜索",value:"skills"},{label:"PPT 生成",value:"ppt"},{label:"PSD 生成",value:"psd"},{label:"对话",value:"chat"}],V=u("帮我搜索 chatgpt2api 相关项目"),h=u(null),$=u(""),w=u(!1),H=u(0),ae=g(()=>`${(H.value/1e3).toFixed(2)}s`),F=u("auto"),M=u(""),x=u("你好，先记住我的项目叫 chatgpt2api。"),b=u([]),O=u(null),P=u(!1),S=u(""),se=g(()=>JSON.stringify(O.value||{messages:[]},null,2)),le=[{label:"默认思考",value:""},{label:"低",value:"low"},{label:"中",value:"medium"},{label:"高",value:"high"},{label:"超高",value:"extended"}],_=u(""),q=u(""),C=u([]),T=u(!1),I=u(!1),k=u(""),j=g(()=>window.location.origin.replace(/\/$/,"")),J=g(()=>be()),re=g(()=>`---
name: chatgpt2api-search
description: 当用户需要联网搜索、查询最新信息、核实事实或需要来源链接时，调用本地 chatgpt2api 搜索接口。
---

# ChatGPT2API 搜索

当用户要求联网搜索、查询最新信息、核实资料、查新闻、查价格、查文档更新或需要来源链接时，使用这个 skill。

## 接口

POST ${j.value}/v1/search

Headers:

Authorization: Bearer ${J.value}
Content-Type: application/json

Body:

{
  "prompt": "<用户要搜索的问题>"
}

## 返回处理

- 使用接口返回的 \`answer\` 作为主要回答。
- 如果有 \`sources\`，在回答里附上来源链接。
- 如果接口报错，简要说明错误并询问是否重试。`),ne=g(()=>`---
name: chatgpt2api-search
description: Use when current web search is needed through this chatgpt2api server. Call the configured HTTP search endpoint with a prompt and return the answer with source URLs.
---

# ChatGPT2API Search

Use this skill when the user asks for current web search, online lookup, recent information, or source-backed answers.

## Request

POST ${j.value}/v1/search

Headers:

Authorization: Bearer ${J.value}
Content-Type: application/json

JSON body:

{
  "prompt": "<search question>"
}

## Response handling

- Use \`answer\` as the main response.
- Include source URLs from \`sources\` when available.
- If the endpoint returns an error, summarize the error and ask whether to retry.`),Z=g(()=>`请帮我在本机安装一个用于联网搜索的 skill。

要求：
1. 按当前环境的 skill 安装规范，把它安装成本地 skill。
2. skill 名称为：chatgpt2api-search
3. 文件名为：SKILL.md
4. 只创建或更新这个 skill 文件，不要修改其他无关文件。

SKILL.md 内容：

\`\`\`markdown
${re.value}
\`\`\``),G=g(()=>`Please install a local web-search skill on this machine.

Requirements:
1. Install this as a local skill according to the current environment's skill rules.
2. Skill name: chatgpt2api-search
3. File name: SKILL.md
4. Only create or update this skill file.

SKILL.md content:

\`\`\`markdown
${ne.value}
\`\`\``),Q=g(()=>p.value==="psd"?"psd":"ppt");me(p,s=>{s==="ppt"?(_.value="生成一个 chatgpt2api 项目架构说明 PPT，包含后端链路、前端控制台、账号池、日志和图片链路。",K()):s==="psd"&&(_.value="生成一个适合控制台产品展示的 PSD 版式，包含概览、账号、日志、图片和代理管理区块。",K())},{immediate:!0});async function W(s){try{await navigator.clipboard.writeText(s),A.success("已复制")}catch{A.error("复制失败")}}async function oe(){const s=V.value.trim();if(!s||w.value)return;const e=Date.now();w.value=!0,$.value="",h.value=null;try{h.value=await R.search(s)}catch(t){$.value=t?.message||"搜索失败"}finally{H.value=Date.now()-e,w.value=!1}}async function ue(){const s=x.value.trim();if(!s||P.value)return;const e=[...b.value,{role:"user",content:s}];b.value=e,x.value="",P.value=!0,S.value="";try{const t=await R.chat(F.value,e,M.value);O.value=t,b.value=[...e,{role:"assistant",content:String(t.choices?.[0]?.message?.content||"")}]}catch(t){S.value=t?.message||"发送失败"}finally{P.value=!1}}function ie(){b.value=[],O.value=null,S.value=""}function X(s){return String(s.taskId||s.id||"")}function de(s){const e=String(s||"queued");return{queued:"排队中",running:"生成中",success:"已完成",error:"失败"}[e]||e}function ce(s){const e=String(s||"").toLowerCase();return e==="success"?"success":e==="error"?"danger":e==="queued"||e==="running"?"warning":"muted"}async function K(){if(!I.value){I.value=!0,k.value="";try{const s=await R.listEditableFileTasks();C.value=(s.items||[]).filter(e=>e.kind===Q.value).slice(0,20)}catch(s){k.value=s?.message||"任务加载失败"}finally{I.value=!1}}}async function ve(){const s=_.value.trim();if(!(!s||T.value)){T.value=!0,k.value="";try{const e=q.value.split(/\r?\n/).map(f=>f.trim()).filter(Boolean),t=await R.createEditableFileTask(Q.value,{prompt:s,base64_images:e});C.value=[t,...C.value].slice(0,20),A.success("任务已提交")}catch(e){k.value=e?.message||"提交失败"}finally{T.value=!1}}}function Y(s){window.open(s,"_blank","noopener,noreferrer")}return(s,e)=>(l(),i("div",ye,[n(E,{class:"debug-center__panel"},{default:r(()=>[n(z,{title:"调试中心"},{copy:r(()=>[...e[9]||(e[9]=[a("p",{class:"mt-1 text-xs text-muted-foreground"},"搜索、Skills、PPT、PSD、对话这些旧调试工具集中在这里。",-1)])]),_:1}),n(_e,{modelValue:p.value,"onUpdate:modelValue":e[0]||(e[0]=t=>p.value=t),options:te,"aria-label":"调试工具"},null,8,["modelValue"])]),_:1}),p.value==="search"?(l(),y(E,{key:0,class:"debug-center__panel"},{default:r(()=>[n(z,{title:"搜索"},{actions:r(()=>[n(v(m),{size:"sm",variant:"primary",disabled:w.value||!V.value.trim(),onClick:oe},{default:r(()=>[d(o(w.value?"搜索中...":"开始搜索"),1)]),_:1},8,["disabled"])]),_:1}),L(a("textarea",{"onUpdate:modelValue":e[1]||(e[1]=t=>V.value=t),class:"debug-textarea",rows:"4",placeholder:"输入要搜索的问题"},null,512),[[U,V.value,void 0,{trim:!0}]]),$.value?(l(),i("div",we,o($.value),1)):c("",!0),h.value?(l(),i("div",xe,[a("div",Pe,[a("div",Se,[n(ee,{tone:"success",shape:"rounded"},{default:r(()=>[d(o(h.value.status||"done"),1)]),_:1}),a("span",null,o(ae.value),1),a("span",null,o(h.value.sources?.length||0)+" sources",1)]),a("div",Ce,o(h.value.answer||"-"),1)]),h.value.sources?.length?(l(),i("div",Te,[e[10]||(e[10]=a("p",{class:"ui-section-kicker"},"来源",-1)),(l(!0),i(B,null,D(h.value.sources,(t,f)=>(l(),i("a",{key:`${t.url||f}`,class:"debug-source-link",href:t.url,target:"_blank",rel:"noopener noreferrer"},[a("span",Le,o(t.title||t.url||"source"),1),a("span",Ee,o(t.url),1)],8,Ie))),128))])):c("",!0)])):c("",!0)]),_:1})):p.value==="skills"?(l(),y(E,{key:1,class:"debug-center__panel"},{default:r(()=>[n(z,{title:"Skills 搜索"},{actions:r(()=>[n(v(m),{size:"sm",variant:"outline",onClick:e[2]||(e[2]=t=>W(Z.value))},{default:r(()=>[...e[11]||(e[11]=[d("复制中文安装指令",-1)])]),_:1}),n(v(m),{size:"sm",variant:"outline",onClick:e[3]||(e[3]=t=>W(G.value))},{default:r(()=>[...e[12]||(e[12]=[d("复制英文安装指令",-1)])]),_:1})]),_:1}),a("div",ze,[a("div",null,[e[13]||(e[13]=a("p",{class:"ui-section-kicker"},"中文安装指令",-1)),n(N,{content:Z.value},null,8,["content"])]),a("div",null,[e[14]||(e[14]=a("p",{class:"ui-section-kicker"},"English install prompt",-1)),n(N,{content:G.value},null,8,["content"])])])]),_:1})):p.value==="ppt"||p.value==="psd"?(l(),y(E,{key:2,class:"debug-center__panel"},{default:r(()=>[n(z,{title:p.value==="ppt"?"PPT 生成":"PSD 生成"},{actions:r(()=>[n(v(m),{size:"sm",variant:"outline",disabled:I.value,onClick:K},{default:r(()=>[d(o(I.value?"刷新中...":"刷新任务"),1)]),_:1},8,["disabled"]),n(v(m),{size:"sm",variant:"primary",disabled:T.value||!_.value.trim(),onClick:ve},{default:r(()=>[d(o(T.value?"提交中...":"提交任务"),1)]),_:1},8,["disabled"])]),_:1},8,["title"]),a("div",Ve,[a("div",$e,[L(a("textarea",{"onUpdate:modelValue":e[4]||(e[4]=t=>_.value=t),class:"debug-textarea",rows:"9",placeholder:"输入生成要求"},null,512),[[U,_.value,void 0,{trim:!0}]]),L(a("textarea",{"onUpdate:modelValue":e[5]||(e[5]=t=>q.value=t),class:"debug-textarea debug-textarea--small",rows:"4",placeholder:"可选：每行一个 base64/data:image 参考图"},null,512),[[U,q.value,void 0,{trim:!0}]]),k.value?(l(),i("div",Ue,o(k.value),1)):c("",!0)]),a("div",Be,[C.value.length===0?(l(),i("div",De,"暂无任务")):c("",!0),(l(!0),i(B,null,D(C.value,t=>(l(),i("article",{key:X(t),class:"debug-task-card"},[a("div",Re,[n(ee,{tone:ce(t.status),shape:"rounded"},{default:r(()=>[d(o(de(t.status)),1)]),_:2},1032,["tone"]),a("span",Ae,o(X(t)),1)]),a("p",Fe,o(t.prompt_preview||"-"),1),t.error?(l(),i("p",Me,o(t.error),1)):c("",!0),t.result?.primary_url||t.result?.zip_url?(l(),i("div",Oe,[t.result?.primary_url?(l(),y(v(m),{key:0,size:"xs",variant:"outline",onClick:f=>Y(t.result.primary_url)},{default:r(()=>[...e[15]||(e[15]=[d("打开结果",-1)])]),_:1},8,["onClick"])):c("",!0),t.result?.zip_url?(l(),y(v(m),{key:1,size:"xs",variant:"outline",onClick:f=>Y(t.result.zip_url)},{default:r(()=>[...e[16]||(e[16]=[d("下载 ZIP",-1)])]),_:1},8,["onClick"])):c("",!0)])):c("",!0)]))),128))])])]),_:1})):(l(),y(E,{key:3,class:"debug-center__panel"},{default:r(()=>[n(z,{title:"对话"},{actions:r(()=>[n(v(m),{size:"sm",variant:"outline",onClick:ie},{default:r(()=>[...e[17]||(e[17]=[d("清空",-1)])]),_:1}),n(v(m),{size:"sm",variant:"primary",disabled:P.value||!x.value.trim(),onClick:ue},{default:r(()=>[d(o(P.value?"发送中...":"发送"),1)]),_:1},8,["disabled"])]),_:1}),a("div",qe,[a("div",Ke,[n(v(ge),{modelValue:F.value,"onUpdate:modelValue":e[6]||(e[6]=t=>F.value=t),modelModifiers:{trim:!0},type:"text",placeholder:"model，例如 auto",block:""},null,8,["modelValue"]),L(a("select",{"onUpdate:modelValue":e[7]||(e[7]=t=>M.value=t),class:"debug-select","aria-label":"思考强度"},[(l(),i(B,null,D(le,t=>a("option",{key:t.value,value:t.value},o(t.label),9,Ne)),64))],512),[[he,M.value]]),L(a("textarea",{"onUpdate:modelValue":e[8]||(e[8]=t=>x.value=t),class:"debug-textarea",rows:"8",placeholder:"输入消息"},null,512),[[U,x.value,void 0,{trim:!0}]]),S.value?(l(),i("div",He,o(S.value),1)):c("",!0),n(N,{content:se.value},null,8,["content"])]),a("div",je,[b.value.length===0?(l(),i("div",Je,"暂无对话消息")):c("",!0),(l(!0),i(B,null,D(b.value,(t,f)=>(l(),i("article",{key:`${t.role}-${f}`,class:"debug-chat-message"},[a("p",Ze,o(t.role),1),a("p",Ge,o(t.content),1)]))),128))])])]),_:1}))]))}}),ot=ke(Qe,[["__scopeId","data-v-e58f1463"]]);export{ot as default};
