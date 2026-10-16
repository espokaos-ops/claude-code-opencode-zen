# OpenCode 1.19.3 — extractos de código (evidencia REA)

Extractos **verbatim** de los módulos descomprimidos del binario de OpenCode 1.19.3 (`/home/kaos/.opencode/bin/opencode`).

## OC-01

**Qué demuestra:** @ai-sdk/openai-compatible: URL = baseURL+path sin normalizar y Authorization: Bearer <apiKey>; POST a /chat/completions.

- Chunk: `chunk-bbwy2mqb.js` (SHA-256 `8626ed26b050906d9d1ba5b0cc3a18b76254142530856b3203c1043b59ce604a`)
- Offset del ancla: 48403

```javascript
n().nullish(),strictJsonSchema:j.boolean().nullish(),textVerbosity:j.enum(["low","medium","high"]).nullish(),user:j.string().nullish()});var B3="0.1.0";function H3(X={}){let U=f0(X.baseURL??"https://api.openai.com/v1");if(!U)throw Error("baseURL is required");let D={...X.apiKey&&{Authorization:`Bearer ${X.apiKey}`},...X.headers},N=()=>A0(D,`ai-sdk/openai-compatible/${B3}`),q=(G)=>{return new p(G,{provider:`${X.name??"openai-compatible"}.chat`,headers:N,url:({path:V})=>`${U}${V}`,fetch:X.fetch})},E=(G)=>{return new a(G,{provider:`${X.name??"openai-compatible"}.responses`,headers:N,url:({path:V})=>`${U}${V}`,fetch:X.fetch})},$=(G)=>q(G),Z=function(G){return q(G)};return Z.languageModel=$,Z.chat=q,Z.responses=E,Z}var k1=H3();export{k1 as openaiCompatible,H3 as createOpenaiCompatible};

```

## OC-02

**Qué demuestra:** Carga del provider opencode: sin credencial se usa apiKey:"public" y se eliminan los modelos con coste > 0 (solo gratuitos).

- Chunk: `chunk-3w3d1rw9.js` (SHA-256 `268e3ddcd57d968e5cd6112f9c797e36b1e04f7a75bbd65ad00396b7f94388aa`)
- Offset del ancla: 39037

```javascript
-oss-safeguard-120b")return J.chat?.(Q)??J.languageModel(Q);return J.responses?.(Q)??J.languageModel(Q)}function kY(J){return{anthropic:()=>z.succeed({autoload:!1,options:{headers:{"anthropic-beta":"interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14"}}}),opencode:z.fnUntraced(function*(Q){let Y=yield*J.env(),X=i(()=>{if(Q.env.some(($)=>Y[$]))return!0;return!1})||Boolean(yield*J.auth(Q.id))||Boolean((yield*J.config()).provider?.opencode?.options?.apiKey);if(!X)for(let[$,Z]of Object.entries(Q.models)){if(Z.cost.input===0)continue;delete Q.models[$]}return{autoload:Object.keys(Q.models).length>0,options:X?{}:{apiKey:"public"}}}),openai:()=>z.succeed({autoload:!1,async getModel(Q,Y,W){return Q.responses(Y)},options:{headerTimeout:MY}}),meta:()=>z.succeed({autoload
```
