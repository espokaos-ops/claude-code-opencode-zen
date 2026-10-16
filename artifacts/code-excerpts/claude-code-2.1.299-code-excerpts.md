# Claude Code 2.1.299 — extractos de código (evidencia REA)

Extractos **verbatim** (minificados) de los chunks descomprimidos del bundle de Claude Code 2.1.299 instalado en el host de investigación.
Los offsets son posiciones de byte dentro del chunk. Los SHA-256 permiten reproducibilidad.

Fuente: `/home/kaos/.local/share/claude/versions/2.1.299` (bun bytecode, extraído a módulos JS con REA).

## CC-01

**Qué demuestra:** Construcción de URL: concatenación literal baseURL + path (sin normalizar /v1).

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 169164

```javascript
buildURL(r,n,s){let h=!_e(this,Qa,"m",Dd).call(this)&&s||this.baseURL,y=Zl(r)?new URL(r):new URL(h+(h.endsWith("/")&&r.startsWith("/")?r.slice(1):r)),w=this.defaultQuery(),S=Object.fromEntries(y.searchParams);if(!Ws(w)||!Ws(S))n={...S,...w,...n};if(typeof n==="object"&&n&&!Array.isArray(n))y.search=this.stringifyQuery(n);return y.toString()}_calculateNonstreamingTimeout(r){if(3600*r/128000>600)throw new Jn("Streaming is required for operations that may take longer than 10 minutes. See https://github.com/anthropics/anthropic-sdk-ty
```

## CC-02

**Qué demuestra:** Parseo de ANTHROPIC_CUSTOM_HEADERS dentro del constructor del cliente SDK: los custom headers se fusionan como base de defaultHeaders.

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 164868

```javascript
),this.middleware=[...w.middleware??[]];let S=n_("ANTHROPIC_CUSTOM_HEADERS");if(S){let R={};for(let I of S.split(`
`)){let P=I.indexOf(":");if(P>=0)R[I.substring(0,P).trim()]=I.substring(P+1).trim()}w.defaultHeaders={...R,...w.defaultHeaders}}let v=y.__auth;if(delete w.__auth,delete w.__baseURLIsExplicit,this._options=w,this.apiKey=typeof n==="string"?n:null,this.authToken=s,this.webhookKey=h,v){if(this._authState=v,!this._baseURLIsExplicit&&v.baseURL)this.baseURL=v.baseURL}else if(this._authState={pr
```

## CC-03

**Qué demuestra:** Nl(): cabeceras por defecto de cada petición — x-app, User-Agent ($0()) y X-Claude-Code-Session-Id (kDt).

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 261689

```javascript
function Nl(){return{"x-app":Ft()?"cli-bg":"cli","User-Agent":$0(),[kDt]:q()}}function wse(){let e=new Set(WTo());return Fa(Nl(),(r,n)=>e.has(n)||ULt(r)!==null)}var Mw=["https://www.googleapis.com/auth/cloud-platform"]
```

## CC-04

**Qué demuestra:** Ensamblado de defaultHeaders del cliente (jF): {...Nl(), ...te(custom headers), ...n$() ...} — los custom headers van DESPUÉS de Nl() y pueden sobrescribir User-Agent.

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 263531

```javascript
te=$Mt(),ie=await gm({querySource:y,permissionContext:R}),ee={...Nl(),...te,...n$(),...F&&{"x-claude-remote-container-id":F},...H&&{"x-claude-remote-session-id":H},...Y&&{[iCr]:Y},...G&&{"x-client-app":G},...W?.agentId&&{"x-claude-code-agent-id":aPr(W.agentId)},...W?.parentAgentId&&{"x-claude-code-parent-agent-id":aPr(W.parentAgentId)},...J&&{[EDt]:J},...Q&&{[oCr]:aPr(Q)},...V&&v!==void 0&&Vt(v)!==null&&{[sCr]:v}};if(t(`[API:request] Creating client, ANTHROPIC_CUSTOM_HEADERS present: ${!!process.env.ANTHROPIC_CUSTOM_HEADERS
```

## CC-05

**Qué demuestra:** Chequeo de credencial del cliente: sin apiKey/OAuth/token → throw K6e.

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 271208

```javascript
();return new twe({apiKey:null,authToken:ge,baseURL:le,...Fe,defaultHeaders:{...be,...Tb(),Authorization:`Bearer ${ge}`,...ae?.extraHeaders,...Dl(ie,be)},...l6()&&{logger:Nt()}})}}if(!yr&&!Se&&!xt(ee).value&&await Yz(I))throw new K6e;if(Be){let oe=Vwe();if(oe)throw new mfe(oe.url);if(fe==="lo
```

## CC-06

**Qué demuestra:** Construcción final del cliente: baseURL = ANTHROPIC_BASE_URL tal cual (sin normalizar) + defaultHeaders ensamblados.

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 272034

```javascript
let ah={apiKey:Go.apiKey,authToken:Go.authToken,...a.ANTHROPIC_BASE_URL?{baseURL:a.ANTHROPIC_BASE_URL}:!1,...Fe,defaultHeaders:Ql,...l6()&&{logger:Nt()}};return new twe(ah)}async function Lw(e,r){let n=gr()&&Sp({skipRetrievingKeyFromApiKeyHelper:!0}).source==="none",h=tw()&&!n?void 0:a.ANTHROPIC_AUTH_TOKEN,y=h||await X3e(r);if(y)return e.Authorization=`Bearer ${y}`,h?"ANTHRO
```

## CC-07

**Qué demuestra:** $Mt(): parseo de la lista de custom headers (ive()), con tratamiento especial de anthropic-beta, Authorization y headers por política.

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 273478

```javascript
function $Mt(){let e={};for(let[n,s]of ive()){if(n.toLowerCase()==="anthropic-beta"&&fU()){t("ANTHROPIC_CUSTOM_HEADERS anthropic-beta ignored: experimental betas are disabled by your organization's policy",{level:"debug"});continue}e[n]=s}let r=c4n();if(r&&!Object.keys(e).some((n)=>/^anthropic-client-(platform|version)$/i.test(n)))e["anthropic-client-platform"]="desktop_app",e["anthropic-client-version"]=r;return e}function etn(){return Math.max(vm()??0,300000)}function vm(){let e=Wj(process.env.CLAUDE_STREAM_IDLE_TIMEOUT_MS);if(e>0)return e;let r=Am("stream_idle_timeout_ms");return r===void 0?void 0:Math.min(r,Hl)}function skr(){return a.API_TIMEOUT_MS??Am("api_timeout_ms")}function Am(e){let r=km()?.[e];return typeof r==="number"&&Number.isInteger(r)&&r>=Ns&&r<=Pu?r:void 0}function km(){return lin()?Tl():null}var Ns=1e4,Hl=1800000,_m=180000;function Fw(e){let n=etn(),s=Wj(process.env.CLAUDE_BYTE_STREAM_IDLE_
```

## CC-08

**Qué demuestra:** mZe(): true si hay variables ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*_MODEL (u otras) — dHe() retorna de inmediato y se omite la validación de modelo.

- Chunk: `chunk-1qwezzd3.js` (SHA-256 `27fbcecc39e0b0bd05a8cae87de5374c1ff91d6d913873471d92a5242dc53992`)
- Offset del ancla: 11424

```javascript
function mZe(){return Boolean(ic()!==void 0||a.ANTHROPIC_MODEL||a.ANTHROPIC_DEFAULT_FABLE_MODEL||a.ANTHROPIC_DEFAULT_OPUS_MODEL||a.ANTHROPIC_DEFAULT_SONNET_MODEL||a.ANTHROPIC_DEFAULT_HAIKU_MODEL||aBe()||!su())}async function dHe(e,r,o,{scheduleTelemetry:n=(l)=>l(),storageV5:s,credentials:u}={}){if(mZe())return;let l=L(e,r),m=l.kind==="declined"&&l.reason==="not_allowed"?await Whe(l.model,s,u):void 0;if(m!==void 0&&mZe())return;let p=m==="overturned"?L(e,r):l;if(p.kind==="none")return;if(p.kind==="mode_dependent_setting"){n(()=>i("tengu_resume_model_restore",{outcome:c("skipped_mode_dependent_setting"),is_eap:!1}));return}if(p.kind==="declined")n(()=>i("tengu_resume_model_restore",{outcome:c("declined"),decline_reason:pe(p.reason),entitlement_reprobe:pe(m),is_eap:Axe(p.model)}));if(p.kind==="declined"){let h=r&&On(r)||"the default model";o?.(`Session model ${p.model} could not be restored (${_e[p.reason]}) \u2014 using ${h} instead.`);return}return p.model}function _jr(e,r){let o=L(e,r);return o.kind==="ok"?o.model:void 0}function Ie(e,r){if(e==="opusplan")return r.includes("opus")||r.includes("sonnet");if(e==="haiku")return r.includes("haiku")||r.includes("sonnet");return!1}function L(e,r){l
```

## CC-09

**Qué demuestra:** Gateway model discovery: condiciones (firstParty + env), construcción de headers con override por custom headers, GET {base}/v1/models?limit=1000.

- Chunk: `chunk-xywp7esx.js` (SHA-256 `d6b4961aceffaacaac4164b7becd1f0dd588c35a7d51a56a12822cd6979fb7b1`)
- Offset del ancla: 294564

```javascript
.label===$C(e.value)}async function tIs(e){if(!Xd()){if(a.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY){let r=Oe();t(`[gatewayDiscovery] skipped: ${r!=="firstParty"?`provider is ${r}`:$ie()?"the base URL is asserted to be the Anthropic API":a.ANTHROPIC_BASE_URL?"ANTHROPIC_BASE_URL is a first-party host":"ANTHROPIC_BASE_URL is unset"}`)}return}let n=a.CLAUDE_CODE_GATEWAY_MODEL_DISCOVERY_TIMEOUT_MS??_N;try{let r=a.ANTHROPIC_BASE_URL;if(!r)return;let s=a.ANTHROPIC_AUTH_TOKEN,h=qEo(),y=s||!h?void 0:(await X3e(ve()))?.trim(),S=s||y,w=VS()?.trim()||y;if(!S&&!w){t(h?"[gatewayDiscovery] skipped: no credential (ANTHROPIC_AUTH_TOKEN, apiKeyHelper, or API key)":"[gatewayDiscovery] skipped: apiKeyHelper requires workspace trust");return}let C=Object.fromEntries(ive().filter(([,te])=>te)),R={...S&&{Authorization:`Bearer ${S}`},...w&&{"x-api-key":w},"anthropic-version":"2023-06-01","User-Agent":Qo()};for(let[te,le]of Object.entries(C)){for(let ae of Object.keys(R))if(ae.toLowerCase()===te.toLowerCase())delete R[ae];R[te]=le}let P=Object.keys(C),N=new Set(P.map((te)=>te.toLowerCase()));aCr({apiKey:N.has("x-api-key")?null:w||null,getApiKeySource:()=>{let{source:te}=Sp({skipRetrievingKeyFromApiKeyHelper:!0});return te!=="none"?te:y?"apiKeyHelper":"unknown"},authToken:null,getAuthTokenSource:()=>"unknown",defaultHeaders:R,authorizationSource:!S||N.has("authorization")?null:s?"ANTHROPIC_AUTH_TOKEN":"apiKeyHelper",customHeaderNames:P,envSuppliedHeaderNames:new Set});let F=`${r.replace(/\/+$/,"")}/v1/models?limit=1000`,H=await fetch(F,{method:"GET",headers:R,redirect:"error",signal:AbortSignal.timeout(n),...aa({url:F})});if(!H.ok){t(`[gatewayDiscovery] non-OK status ${H.status}`);return}let G=await H.json(),Q=u({data:T(pb())}).safeParse(G);if(!Q.success){t("[gatewayDiscovery] response body failed validation");return}let V=Q.data.data.filter((te)=>/(claude|anthropic)/i.test(te.id));if(V.length===0){t("[gatewayDiscovery] 0 usable m
```

## CC-10

**Qué demuestra:** Constante kDt = X-Claude-Code-Session-Id (cabecera de sesión de CC).

- Chunk: `chunk-xywp7esx.js` (SHA-256 `d6b4961aceffaacaac4164b7becd1f0dd588c35a7d51a56a12822cd6979fb7b1`)
- Offset del ancla: 271207

```javascript
th("agent:custom"))return"custom";return}var sCr="x-claude-code-prompt-id";var iCr="x-claude-remote-session-origin";var kDt="X-Claude-Code-Session-Id";class m5 extends x{header;source;constructor(e,n,r){super(e
```

## CC-11

**Qué demuestra:** $0(): User-Agent de Claude Code (claude-cli/2.1.299 …).

- Chunk: `chunk-xywp7esx.js` (SHA-256 `d6b4961aceffaacaac4164b7becd1f0dd588c35a7d51a56a12822cd6979fb7b1`)
- Offset del ancla: 474428

```javascript
function $0(){let e=process.env.CLAUDE_AGENT_SDK_VERSION?`, agent-sdk/${process.env.CLAUDE_AGENT_SDK_VERSION}`:"",n=a.CLAUDE_AGENT_SDK_CLIENT_APP?`, client-app/${a.CLAUDE_AGENT_SDK_CLIENT_APP}`:"",r=aRr(),s=r?`, workload/${r}`:"";return`claude-cli/${{ISSUES_EXPLAINER:"report the issue at https://github.com/anthropics/claude-code/issues",PACKAGE_URL:"@anthropic-ai/claude-code",README_URL:"https://code.claude.com/docs/en/overview",VERSION:"2.1.299",FEEDBACK_CHANNEL:"https://github.co
```

## CC-12

**Qué demuestra:** Validación de cambio de modelo (model_switch): ids no reconocidos → bloqueo con error.

- Chunk: `chunk-jtbwa3j2.js` (SHA-256 `f24eb8039255226da38543878c5341be1bf1131334df6c2b4bc6fc26778bba3c`)
- Offset del ancla: 27724

```javascript
ed",underEnforcement:r!==null}:{kind:"steppedDown",model:s}}function opn(e,n){let r=_t(e);if(r.recognized)return;return i("tengu_set_model_unrecognized",{shape:c(r.shape),had_suggestion:r.suggestion!==void 0,surface:n}),m("model_switch","unrecognized_model"),{ok:!1,error:wt(r_(e),r.suggestion)}}var Hr=5000;function St(e,n){return m("system_prompt_switch",n),{ok:!1,error:e,code:n}}async function UUo(e,n){let r=e.model;if(r!=null&&typeof r!=="string"){if(m("model_switch","invalid_model_type"),e.system_prompt!==void 0)m("system_prompt_switch","model_switch_rejected");return{ok:!1,error:"set_model: model must be a string",code:"invalid_request"}}let s=e.system_prompt;if(s!==void 0&&(typeof s!=="string"||s===""))return m("system_prompt_switch",typeof s!=="string"?"invalid_type":"empty"),{ok:!1,error:"set_model: system_prompt must be a non-emp
```

## CC-13

**Qué demuestra:** Señal de telemetría unrecognized_model (IIo/sge) — no es un bloqueo duro.

- Chunk: `chunk-84yp45y8.js` (SHA-256 `90753a793616ab8ad573768c8ce35f70a402475afc1deab0221b20d198cfb0da`)
- Offset del ancla: 1510742

```javascript
IIo="[claude-code:unrecognized_model]";function sge(e,n){try{if(n==="model_validation")return;if(WUe(e))return;let r=On(e);if(!Ji().claim(`unrecognized-model-signal:${r}`))return;if(zpe(e)||zpe(r))return;i("tengu_api_unrecognized_model",{model:Et(e),querySource:ns(n)});let s=`${IIo} ${_({model:e,query_source:n})}`.replace(gae,"");if(LX()!==null&&a.CLAUDE_CODE_SESSION_KIND!=="bg")Fj(`${s}
`);else t(s,{level:"warn"})}catch(r){d(Je(j(r),"unrecognized-model signal failed"))}}async function oF(e){F1t++;try{return await DIo(e)}finally{F1t--}}var F1t=0;async function DIo(e){let{model:n,system:r,messages:s,tools:h,tool_choice:y,output_format:S,max_tokens:w=1024,maxRetries:H=2,timeout:G,signal:V,skipSystemPromptPrefix:Q,forceAttributionH
```

## CC-14

**Qué demuestra:** Uso de /v1/messages/cache_touch (keepalive).

- Chunk: `chunk-84yp45y8.js` (SHA-256 `90753a793616ab8ad573768c8ce35f70a402475afc1deab0221b20d198cfb0da`)
- Offset del ancla: 217858

```javascript
=void 0}let h=L(s)?s.type:void 0;if(typeof h==="string"&&h.startsWith(dyt))return;if(typeof h!=="string"||e.includes(W9n))return _({type:"line-withheld",bytes:Buffer.byteLength(e)});return e}var z9n="tengu_sequential_cloud",q9n="anthropic-cache-keepalive",K9n="/v1/messages/cache_touch",NIe=1e4,V9n=3,Y9n=3,X9n=3,eY=T1,uyt=eY-NIe,Q9n=3600000,J9n=240000,Z9n=["main_request","user_input","work_start","work_end","awaiting_user_start","awaiting_user_end"],e8n=p(()=>u({enabled:A(!0),touchIntervalSeconds:v().min(10).max(120).default(30),activityWind
```

## CC-15

**Qué demuestra:** Path /v1/messages/count_tokens en el SDK (hay variante ?beta=true).

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 160935

```javascript
{return Ud.createMessage(this,r,n,{logger:this._client.logger??console})}countTokens(r,n){let{user_profile_id:s,workspace_id:h,...y}=r;return this._client.post("/v1/messages/count_tokens",{body:y,...n,headers:M([{...s!=null?{"anthropic-user-profile-id":s}:void 0,...h!=null?{"anthropic-workspace-id":h}:void 0},n?.headers])})}}return e.Batches=Mo,
```

## CC-16

**Qué demuestra:** validateHeaders(): mapeo de credenciales a cabeceras (x-api-key / authorization).

- Chunk: `chunk-gmq0qwep.js` (SHA-256 `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5`)
- Offset del ancla: 167774

```javascript
tion=null}}defaultQuery(){return this._options.defaultQuery}validateHeaders({values:r,nulls:n}){if(r.get("x-api-key")||r.get("authorization"))return;if(this._authState.error)throw this._authState.error;if(this._authState.tokenCache||this._authState.resolution)return;if(this.apiKey&&r.get("x-api-key"))return;if(n.has("x-api-key"))return;if(this.authToken&&r.get("authorization"))return;if(n.has("authorization"))return;throw Error('Could not resolve authentication method. Expected one of apiKey
```
