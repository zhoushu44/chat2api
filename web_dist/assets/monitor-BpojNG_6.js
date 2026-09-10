import{q as t}from"./index-CFE-nKHk.js";const r={uptime(e=90){return t.get("/public/uptime",{params:{days:e}})},realtime(){return t.get("/api/monitor/realtime")}};export{r as m};
